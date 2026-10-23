"""#492 S7: `POST /recording/symbols` and `PUT /recording/symbols/{id}/pin` over a bare app, the
fake control behind them. RBAC first (403 with `rbac.denied`, AC5), a user actor, the per-user
write limit (429), the key and body (422), the store (503), the `recorder` step-up where a write
changes retention, a replay, the entry in the settings' env (404), then the write, audited
ahead of the store. A non-Owner reads every answer through the restricted view."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from candleviewer.api import recording_writes as writes
from candleviewer.api.recording_symbols import make_recording_symbols_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.recorder import control as rc
from tests.unit.recorder._control_fakes import NOW, STREAMS, FakeRecorder

W = ("recording:read", "recording:write")
_ADD = "/recording/symbols"


def _pin(entry_id: str) -> str:
    return f"/recording/symbols/{entry_id}/pin"


class _Env:
    """The app over `fake`; the env resolves the caller, keeps the audit and the step-up."""

    def __init__(self, fake: FakeRecorder | None, *perms: str, owner: bool = True,
                 elevated: bool = False) -> None:  # fmt: skip
        self.fake = FakeRecorder() if fake is None else fake
        self.fake.audit = self  # the policy's own records (#2188 S2b), written ahead of the row
        self.writer: FakeRecorder | None = self.fake
        self.caller = AuditPrincipal(uuid.uuid4(), "u", frozenset(perms), is_owner=owner)
        self.audit: list[tuple[str, dict[str, Any]]] = []
        self.elevated, self.fail_audit, self.now = elevated, False, 0.0
        self.listed = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        app = FastAPI()
        limiter = writes.WriteLimiter(clock=lambda: self.now)
        app.include_router(writes.make_recording_writes_router(
            lambda: self.writer, self, self, self.elevate, self.listed.__contains__,
            limiter=limiter))  # fmt: skip
        app.include_router(make_recording_symbols_router(lambda: self.fake, self, self))
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def resolve(self, request: Any) -> AuditPrincipal | None:
        return self.caller if self.caller.permissions else None

    async def emit(self, action: str, **kwargs: Any) -> None:
        if self.fail_audit:
            raise AuditUnavailable("full")
        self.audit.append((action, kwargs))

    async def elevate(self, session_id: uuid.UUID | None) -> JSONResponse | None:
        refused = {"code": "step_up_required", "action_class": "recorder", "status": 403}
        return None if self.elevated else JSONResponse(refused, 403)

    def actions(self) -> list[str]:
        return [action for action, _ in self.audit]

    async def add(self, **body: Any) -> httpx.Response:
        return await self.http.post(_ADD, json=body)


async def test_no_session_is_401_and_a_viewer_add_is_403_audited_as_rbac_denied() -> None:
    assert (await _Env(None).add(symbol="BTCUSDT")).status_code == 401
    viewer = _Env(None, "recording:read", owner=False)
    refused = await viewer.add(symbol="BTCUSDT")
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    assert viewer.actions() == ["rbac.denied"] and viewer.fake.entries == {}


async def test_a_plain_add_needs_no_step_up_and_answers_201_with_an_estimate() -> None:
    env = _Env(None, *W)
    created = await env.add(symbol="SOLUSDT")
    body = created.json()
    assert created.status_code == 201 and env.actions() == ["recorder.start"]
    assert (body["symbol"], body["reason"], body["pinned"]) == ("SOLUSDT", "manual", False)
    assert (body["streams"], body["depth"], body["estimate"]["warning"]) == (
        list(STREAMS),
        200,
        None,
    )
    assert body["added_by"] == str(env.caller.user_id)
    assert (await env.add(symbol="BTCUSDT", depth=500)).json()["estimate"]["warning"]


@pytest.mark.parametrize(
    "extra", [{"pinned": True}, {"pinned": False}, {"retention_days": 7}, {"retention_days": None}]
)
async def test_pinned_or_retention_days_on_an_add_needs_the_recorder_step_up(extra: Any) -> None:
    env = _Env(None, *W)
    refused = await env.add(symbol="SOLUSDT", **extra)
    assert (refused.status_code, refused.json()["code"]) == (403, "step_up_required")
    assert env.fake.entries == {} and env.actions() == []
    env.elevated = True
    assert (await env.add(symbol="SOLUSDT", **extra)).status_code == 201


async def test_a_pinned_add_keeps_forever() -> None:
    env = _Env(None, *W, elevated=True)
    body = (await env.add(symbol="SOLUSDT", pinned=True, retention_days=9)).json()
    assert (body["pinned"], body["retention_days"]) == (True, None)


async def test_the_cap_is_422_and_a_re_add_answers_200_with_the_row() -> None:
    env = _Env(FakeRecorder(max_symbols=1), *W)
    first, again = [await env.add(symbol="BTCUSDT") for _ in range(2)]
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == {k: v for k, v in first.json().items() if k != "estimate"}
    capped = await env.add(symbol="ETHUSDT")
    assert (capped.status_code, capped.json()["code"]) == (422, "recorder_symbol_limit")
    assert list(env.fake.entries) == ["BTCUSDT"] and env.actions()[-1] == "recorder.start"
    assert (env.audit[-1][1]["outcome"], env.audit[-1][1]["reason"]) == (
        "denied", "recorder_symbol_limit")  # fmt: skip


async def test_a_key_replays_its_answer_and_another_body_under_it_is_409() -> None:
    env = _Env(None, *W)
    key = {"Idempotency-Key": str(uuid.uuid4())}
    first, again = [await env.http.post(_ADD, json={"symbol": "BTCUSDT"}, headers=key)
                    for _ in range(2)]  # fmt: skip
    assert (again.status_code, again.content) == (201, first.content)
    assert again.headers["Idempotency-Replayed"] == "true" and env.actions() == ["recorder.start"]
    other = await env.http.post(_ADD, json={"symbol": "ETHUSDT"}, headers=key)
    assert (other.status_code, other.json()["code"]) == (409, "idempotency_key_reuse")
    bad = await env.http.post(_ADD, json={"symbol": "ETHUSDT"}, headers={"Idempotency-Key": "x"})
    assert (bad.status_code, bad.json()["code"]) == (422, "validation_failed")
    assert list(env.fake.entries) == ["BTCUSDT"]


async def test_no_control_is_503_and_an_unlisted_symbol_or_a_bad_body_is_422() -> None:
    env = _Env(None, *W)
    env.writer = None
    unbound = await env.add(symbol="BTCUSDT")
    assert (unbound.status_code, unbound.json()["code"]) == (503, "store_unavailable")
    env.writer = env.fake
    unlisted = await env.add(symbol="DOGEUSDT")
    assert (unlisted.status_code, unlisted.json()["errors"][0]["rule"]) == (
        422,
        "listed_instrument",
    )
    bodies: list[Any] = [{"symbol": "btc"}, {"symbol": "BTCUSDT", "depth": 7}, [], "x"]
    for bad in [*bodies, {"symbol": "BTCUSDT", "archive_path": "/x"}]:
        answer = await env.http.post(_ADD, json=bad)
        assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert (await env.http.post(_ADD, content=b"")).status_code == 422
    assert env.fake.entries == {} and env.actions() == []


async def test_an_add_is_audited_ahead_and_a_refused_record_adds_nothing() -> None:
    env = _Env(None, *W)
    env.fail_audit = True
    refused = await env.add(symbol="BTCUSDT")
    assert (refused.status_code, refused.json()["code"]) == (503, "audit_unavailable")
    assert env.fake.entries == {}


async def test_an_actor_that_is_no_user_uuid_is_refused() -> None:
    env = _Env(None, *W)
    env.caller = dataclasses.replace(env.caller, user_id="svc-recorder")  # type: ignore[arg-type]
    refused = await env.add(symbol="BTCUSDT")
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    assert env.fake.entries == {} and env.actions() == []


async def test_past_the_per_user_write_limit_a_write_is_429_with_retry_after() -> None:
    env = _Env(None, *W)
    first = env.caller
    assert {(await env.add(symbol="BTCUSDT")).status_code for _ in range(30)} == {200, 201}
    limited = await env.add(symbol="BTCUSDT")
    assert (limited.status_code, limited.json()["code"]) == (429, "rate_limited")
    assert limited.headers["Retry-After"] == "60" and limited.json()["retry_after_seconds"] == 60
    env.caller = dataclasses.replace(first, user_id=uuid.uuid4())  # another user: its own budget
    assert (await env.add(symbol="BTCUSDT")).status_code == 200
    env.now, env.caller = 60.0, first
    assert (await env.add(symbol="BTCUSDT")).status_code == 200


def test_the_write_limiter_keeps_at_most_its_tracked_users() -> None:
    limiter = writes.WriteLimiter(rate_per_minute=1, tracked_users=2, clock=lambda: 0.0)
    assert [limiter.admit(user) for user in "abc"] == [None, None, None]
    assert len(limiter) == 2 and limiter.admit("c") == 60 and limiter.admit("a") is None


async def test_a_pin_always_needs_the_recorder_step_up_and_the_policy_records_it() -> None:
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT")
    env = _Env(fake, *W)
    refused = await env.http.put(_pin(entry.id), json={"pinned": True})
    assert (refused.status_code, refused.json()["code"]) == (403, "step_up_required")
    assert not fake.entries["BTCUSDT"].pinned and env.actions() == []
    env.elevated = True
    pinned = await env.http.put(_pin(entry.id), json={"pinned": True})
    assert (pinned.status_code, pinned.json()["pinned"]) == (200, True)
    assert fake.entries["BTCUSDT"].pinned and env.actions() == ["retention.change"]
    record = env.audit[0][1]  # the policy's record; the route writes none of its own
    assert (record["reason"], record["after_state"]["pinned"]) == ("pin", True)
    for bad in (
        {},
        {"pinned": "yes"},
        {"pinned": True, "x": 1},
        {"pinned": False, "retention_days": 0},
    ):
        assert (await env.http.put(_pin(entry.id), json=bad)).status_code == 422


async def test_an_unpin_is_audited_before_the_store_and_a_refused_record_changes_nothing() -> None:
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", state="stopped", pinned=True)
    env = _Env(fake, *W, elevated=True)
    env.fail_audit = True
    refused = await env.http.put(_pin(entry.id), json={"pinned": False})
    assert (refused.status_code, refused.json()["code"]) == (503, "audit_unavailable")
    assert fake.entries["BTCUSDT"].pinned
    env.fail_audit = False
    unpinned = await env.http.put(_pin(entry.id), json={"pinned": False, "retention_days": 7})
    assert (unpinned.json()["pinned"], unpinned.json()["retention_days"]) == (False, 7)
    assert "BTCUSDT" not in fake.entries  # an idle row unpinned goes


class _Gone(FakeRecorder):
    """The row goes between the lookup and the pin: the policy finds no active row."""

    async def set_pin(self, symbol: str, pinned: bool, actor: Any) -> None:
        self.entries.clear()
        await super().set_pin(symbol, pinned, actor)  # raises: no active row


async def test_a_pin_of_a_row_gone_since_the_lookup_is_404_audited_as_denied() -> None:
    fake = _Gone()
    entry = fake.put("BTCUSDT")
    env = _Env(fake, *W, elevated=True)
    gone = await env.http.put(_pin(entry.id), json={"pinned": True})
    assert (gone.status_code, gone.json()["code"]) == (404, "not_found")
    assert (env.actions(), env.audit[-1][1]["outcome"]) == (["retention.change"], "denied")


class _OtherEnv(FakeRecorder):
    """A control whose lookup (bound to the settings' env, C-2.11) finds no such id."""

    async def get(self, entry_id: str) -> Any:
        return None


_WRITES_BY_ID = [("PUT", "/pin", {"pinned": True})]


@pytest.mark.parametrize(("method", "suffix", "body"), _WRITES_BY_ID)
async def test_another_environments_id_is_404_and_nothing_is_written(
    method: str, suffix: str, body: Any
) -> None:
    fake = _OtherEnv()
    entry = fake.put("BTCUSDT", "manual", "chart_open")
    env = _Env(fake, *W, elevated=True)
    for entry_id in (entry.id, "not-a-uuid"):
        path = f"/recording/symbols/{entry_id}{suffix}"
        answer = await env.http.request(method, path, json=body)
        assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
    assert fake.entries["BTCUSDT"] == entry and env.actions() == []


async def test_a_non_owner_reads_its_write_through_the_restricted_view() -> None:
    fake = FakeRecorder()
    fake.put("SOLUSDT", "manual", "position_open", refusals=("position_open",))
    env = _Env(fake, *W, owner=False)
    again = await env.add(symbol="SOLUSDT")
    assert again.status_code == 200 and "position_open" not in again.text
    hidden = fake.put("XRPUSDT", "position_open")
    env.elevated = True
    assert (await env.http.put(_pin(hidden.id), json={"pinned": True})).status_code == 404
    assert not fake.entries["XRPUSDT"].pinned


@pytest.mark.parametrize("cause", sorted(rc.HIDDEN_CAUSES))
async def test_a_non_owner_re_add_of_a_row_its_view_does_not_hold_reads_as_a_fresh_add(
    cause: Any,
) -> None:
    """Restricted refusal parity: `201` and the fresh-add body, none of the row's settings or
    session; the server re-adds the row (its pin stays) and the record names what held it."""
    fresh = _Env(None, *W, owner=False)
    fake = FakeRecorder()
    fake.put("SOLUSDT", cause, pinned=True, depth=500, streams=("trades",), started_at=NOW,
             refusals=(cause,))  # fmt: skip
    env = _Env(fake, *W, owner=False)
    env.caller = fresh.caller
    first, again = await fresh.add(symbol="SOLUSDT"), await env.add(symbol="SOLUSDT")
    assert (again.status_code, again.content) == (201, first.content)
    assert fake.entries["SOLUSDT"].pinned and fake.entries["SOLUSDT"].reasons == ("manual", cause)
    assert env.actions() == ["recorder.start"] == fresh.actions()
    held_by = [e.audit[0][1]["after_state"]["held_by"] for e in (env, fresh)]
    assert held_by == [cause, None]  # the record carries the real outcome
    owner = _Env(fake, *W)
    seen = await owner.add(symbol="SOLUSDT")
    assert (seen.status_code, seen.json()["pinned"], seen.json()["depth"]) == (200, True, 500)
