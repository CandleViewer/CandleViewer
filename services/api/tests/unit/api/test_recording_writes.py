"""#492 S7: `POST /recording/symbols` and `PUT /recording/symbols/{id}/pin` over a bare app, the
fake control behind them. RBAC first (403 with `rbac.denied`, AC5), a user actor, the per-user
write limit (429), the key and body (422), the store (503), the `recorder` step-up where a write
changes retention, a replay, the entry in the settings' env (404), then the write, which the
policy records ahead of the store. A non-Owner reads every answer through the restricted view."""

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
from candleviewer.recorder import policy
from candleviewer.recorder.errors import RecorderInvalidUpdateError
from candleviewer.recorder.models import Actor
from candleviewer.recorder.sessions import DEFAULT_STREAMS
from tests.unit.recorder._control_fakes import NOW, STREAMS, FakeRecorder

W = ("recording:read", "recording:write")
_ADD, _PIN = "/recording/symbols", "/recording/symbols/{}/pin"


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
    assert body.items() >= dict(symbol="SOLUSDT", reason="manual", pinned=False, depth=200).items()
    assert (body["streams"], body["estimate"]["warning"]) == (list(STREAMS), None)
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
    assert list(env.fake.entries) == ["BTCUSDT"] and env.actions() == ["recorder.start"] * 2
    assert env.audit[-1][1].items() >= {("outcome", "denied"), ("reason", "recorder_symbol_limit")}
    env.elevated, env.audit = True, []
    await env.add(symbol="ETHUSDT", retention_days=7)  # the retention record's denied twin first
    assert [(a, r.get("outcome"), r.get("reason")) for a, r in env.audit] == [
        ("retention.change", None, None), ("retention.change", "denied", "recorder_symbol_limit"),
        ("recorder.start", "denied", "recorder_symbol_limit")]  # fmt: skip


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


async def test_no_control_is_503_and_an_unlisted_symbol_or_a_bad_body_is_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _Env(None, *W)
    env.writer = None
    unbound = await env.add(symbol="BTCUSDT")
    assert (unbound.status_code, unbound.json()["code"]) == (503, "store_unavailable")
    env.writer = env.fake
    unlisted = await env.add(symbol="DOGEUSDT")
    rule = unlisted.json()["errors"][0]["rule"]
    assert (unlisted.status_code, rule) == (422, "listed_instrument")
    bodies: list[Any] = [{"symbol": "btc"}, {"symbol": "BTCUSDT", "depth": 7}, [], "x"]
    for bad in [*bodies, {"symbol": "BTCUSDT", "archive_path": "/x"}]:
        answer = await env.http.post(_ADD, json=bad)
        assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert (await env.http.post(_ADD, content=b"")).status_code == 422
    monkeypatch.setattr(policy, "STREAM_KINDS", frozenset({"trades"}))  # the policy's own check
    refused = await env.add(symbol="BTCUSDT", streams=["tickers"])
    assert refused.json()["errors"] == [{"field": "streams", "rule": "stream_names",
                                         "message": "Refused by the recorder."}]  # fmt: skip
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
    refused = await env.http.put(_PIN.format(entry.id), json={"pinned": True})
    assert (refused.status_code, refused.json()["code"]) == (403, "step_up_required")
    assert not fake.entries["BTCUSDT"].pinned and env.actions() == []
    env.elevated = True
    pinned = await env.http.put(_PIN.format(entry.id), json={"pinned": True})
    assert (pinned.status_code, pinned.json()["pinned"]) == (200, True)
    assert fake.entries["BTCUSDT"].pinned and env.actions() == ["retention.change"]
    record = env.audit[0][1]  # the policy's record; the route writes none of its own
    assert (record["reason"], record["after_state"]["pinned"]) == ("pin", True)
    for bad in ({}, {"pinned": "yes"}, {"pinned": True, "x": 1},
                {"pinned": False, "retention_days": 0}):  # fmt: skip
        assert (await env.http.put(_PIN.format(entry.id), json=bad)).status_code == 422


async def test_an_unpin_is_audited_before_the_store_and_a_refused_record_changes_nothing() -> None:
    """ETHUSDT: `retention_days` with no pin change; no policy member records it, the route does."""
    fake, days = FakeRecorder(), {"pinned": False, "retention_days": 7}
    entry = fake.put("BTCUSDT", state="stopped", pinned=True)
    kept = fake.put("ETHUSDT", retention_days=9)
    env = _Env(fake, *W, elevated=True)
    env.fail_audit = True
    for row, body in ((entry, {"pinned": False}), (kept, days)):
        refused = await env.http.put(_PIN.format(row.id), json=body)
        assert (refused.status_code, refused.json()["code"]) == (503, "audit_unavailable")
    assert fake.entries == {"BTCUSDT": entry, "ETHUSDT": kept}
    env.fail_audit = False
    assert (await env.http.put(_PIN.format(kept.id), json=days)).json()["retention_days"] == 7
    after = [(a, r["before_state"], r["after_state"]) for a, r in env.audit]
    assert after == [("retention.change", {"retention_days": 9}, {"retention_days": 7})]
    unpinned = await env.http.put(_PIN.format(entry.id), json=days)
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
    gone = await env.http.put(_PIN.format(entry.id), json={"pinned": True})
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
    assert env.actions() == []  # an authorized re-add of a manual entry: no record
    hidden = fake.put("XRPUSDT", "position_open")
    env.elevated = True
    assert (await env.http.put(_PIN.format(hidden.id), json={"pinned": True})).status_code == 404
    assert not fake.entries["XRPUSDT"].pinned


class _Spied(FakeRecorder):
    """Keeps every spec the route hands the port's `add`, as the real port will forward it."""

    def __init__(self) -> None:
        super().__init__()
        self.specs: list[rc.EntrySpec] = []

    async def add(self, symbol: str, spec: rc.EntrySpec, actor: Any) -> Any:
        self.specs.append(spec)
        return await super().add(symbol, spec, actor)


_JOINS: list[dict[str, Any]] = [
    {},
    {"pinned": False},
    {"retention_days": 7},
    {"pinned": False, "retention_days": 7},
    {"pinned": True},
    {"depth": 500, "streams": ["trades"]},
]


@pytest.mark.parametrize("kept", [{"pinned": True}, {"retention_days": 90}])
@pytest.mark.parametrize("extra", _JOINS)
@pytest.mark.parametrize("cause", sorted(rc.HIDDEN_CAUSES))
async def test_a_non_owner_re_add_of_a_row_its_view_hides_joins_it_and_keeps_its_settings(
    cause: Any, extra: dict[str, Any], kept: dict[str, Any]
) -> None:
    """Ruling (iii): the caller's manual cause joins the row through the normal add, `200` with
    the row as the caller's view shows it. A join changes none of the row's settings (no lower
    retention, no unpin); a named pin or retention it does not honour gets its denied twin."""
    fake = _Spied()
    held = fake.put("SOLUSDT", cause, depth=50, streams=("trades", "tickers"), started_at=NOW,
                    refusals=(cause,), **kept)  # fmt: skip
    env = _Env(fake, *W, owner=False, elevated=True)
    joined = await env.add(symbol="SOLUSDT", **extra)
    row = fake.entries["SOLUSDT"]
    assert (joined.status_code, row.reasons) == (200, ("manual", cause))
    assert cause not in joined.text and "estimate" not in joined.json()
    assert joined.json() == (await env.http.get(f"/recording/symbols/{held.id}")).json()
    assert (row.pinned, row.retention_days, row.depth, row.streams) == (
        held.pinned, held.retention_days, 50, ("trades", "tickers"))  # fmt: skip
    named = bool(extra.keys() & {"pinned", "retention_days"})  # not honoured: its denied twin
    assert env.actions() == ["retention.change"] * named + ["recorder.start"]
    record = env.audit[-1][1]  # the policy's own add record, the joined cause in it
    assert (record["outcome"], record["reason"]) == ("success", "manual")
    assert record["after_state"]["trigger_ref"] == f"manual:{env.caller.user_id}"
    assert fake.specs == [rc.EntrySpec(("trades", "tickers"), 50, None, None)]  # the row's own


@pytest.mark.parametrize("cause", sorted(rc.HIDDEN_CAUSES))
async def test_a_join_at_the_cap_is_200_and_the_owner_sees_the_joined_cause(cause: Any) -> None:
    """A join adds no row, so the cap does not refuse it; the Owner's view names the caller's
    manual cause on the row the hidden cause held."""
    fake = FakeRecorder(max_symbols=1)
    held = fake.put("SOLUSDT", cause, streams=STREAMS, refusals=(cause,))
    env = _Env(fake, *W, owner=False)
    assert (await env.add(symbol="SOLUSDT")).status_code == 200
    seen = (await _Env(fake, *W).http.get(f"/recording/symbols/{held.id}")).json()
    assert (seen["reason"], seen["added_by"], seen["refusal"]) == (
        "manual", str(env.caller.user_id), cause)  # fmt: skip


@pytest.mark.parametrize("cause", sorted(rc.HIDDEN_CAUSES))
async def test_a_join_whose_record_cannot_be_written_is_503_and_changes_nothing(cause: Any) -> None:
    fake = FakeRecorder()
    held = fake.put("SOLUSDT", cause, streams=STREAMS, refusals=(cause,))
    env = _Env(fake, *W, owner=False)
    env.fail_audit = True
    refused = await env.add(symbol="SOLUSDT")
    assert (refused.status_code, refused.json()["code"]) == (503, "audit_unavailable")
    assert fake.entries["SOLUSDT"] == held


@pytest.mark.parametrize("cause", sorted(rc.HIDDEN_CAUSES))
async def test_a_join_of_a_row_with_no_stored_streams_is_503_and_joins_nothing(cause: Any) -> None:
    """The status carries the stored row's streams; none means no stored row to keep them from,
    so the route refuses rather than let the policy name its default streams on the row."""
    fake = FakeRecorder()
    held = fake.put("SOLUSDT", cause)  # the seed's default: no streams
    env = _Env(fake, *W, owner=False)
    refused = await env.add(symbol="SOLUSDT")
    assert (refused.status_code, refused.json()["code"]) == (503, "store_unavailable")
    assert fake.entries["SOLUSDT"] == held and env.actions() == []


@pytest.mark.parametrize("cause", sorted(rc.HIDDEN_CAUSES))
async def test_a_join_naming_pinned_without_the_step_up_is_403_and_records_nothing(
    cause: Any,
) -> None:
    fake = FakeRecorder()
    held = fake.put("SOLUSDT", cause, streams=STREAMS, refusals=(cause,))
    env = _Env(fake, *W, owner=False)
    refused = await env.add(symbol="SOLUSDT", pinned=True)
    assert (refused.status_code, refused.json()["code"]) == (403, "step_up_required")
    assert fake.entries["SOLUSDT"] == held and env.actions() == []


@pytest.mark.parametrize("cause", sorted(rc.HIDDEN_CAUSES))
@pytest.mark.parametrize("extra", [{"retention_days": 7}, {"pinned": True}])
async def test_a_join_naming_retention_records_its_denied_twin_ahead(
    extra: dict[str, Any], cause: Any
) -> None:
    """The route records the request (C-2.9): a join honours no named pin or retention, so it
    writes the denied `retention.change` first, ids only, reason `joined`; the 200 is the
    same as a plain join's. Unwritten: 503 and nothing changes."""
    plain_fake, fake = FakeRecorder(), FakeRecorder()
    plain_fake.put("SOLUSDT", cause, streams=STREAMS, retention_days=90)
    held = fake.put("SOLUSDT", cause, streams=STREAMS, retention_days=90)
    env, plain = _Env(fake, *W, owner=False, elevated=True), _Env(plain_fake, *W, owner=False)
    plain.caller = env.caller
    env.fail_audit = True
    refused = await env.add(symbol="SOLUSDT", **extra)
    assert (refused.status_code, refused.json()["code"], fake.entries["SOLUSDT"]) == (
        503, "audit_unavailable", held)  # fmt: skip
    env.fail_audit = False
    joined, alone = await env.add(symbol="SOLUSDT", **extra), await plain.add(symbol="SOLUSDT")
    assert (joined.status_code, joined.content) == (200, alone.content)
    action, record = env.audit[0]
    assert (action, record["outcome"], record["reason"], record["object_id"]) == (
        "retention.change", "denied", "joined", held.id)  # fmt: skip
    assert "before_state" not in record and "after_state" not in record
    assert env.actions() == ["retention.change", "recorder.start"]


async def test_the_fake_promotes_a_held_row_as_the_policy_does() -> None:
    """`add_manual` on a row another cause holds (upsert_manual's promotion): the named streams,
    else the policy's default; the named depth, else the row's; the pin, retention kept."""
    fake = FakeRecorder()
    fake.put("SOLUSDT", "chart_open", depth=50, streams=("trades",), pinned=True)
    await fake.add_manual("SOLUSDT", Actor(kind="user", id="u-1"))
    row = fake.entries["SOLUSDT"]
    assert (row.streams, row.depth, row.pinned, row.added_by) == (DEFAULT_STREAMS, 50, True, "u-1")


async def test_an_add_naming_retention_days_the_policy_refuses_writes_only_the_denied_twin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`RecorderInvalidUpdateError` refuses before the policy records: the route's retention
    record and its denied twin, no `recorder.start`, `422`."""
    monkeypatch.setattr(policy, "STREAM_KINDS", frozenset({"trades"}))
    env = _Env(None, *W, elevated=True)
    refused = await env.add(symbol="SOLUSDT", streams=["tickers"], retention_days=7)
    assert (refused.status_code, refused.json()["code"]) == (422, "validation_failed")
    assert refused.json()["errors"][0]["rule"] == "stream_names" and env.fake.entries == {}
    assert [(a, r.get("outcome"), r.get("reason")) for a, r in env.audit] == [
        ("retention.change", None, None),
        ("retention.change", "denied", "stream_names"),
    ]


@pytest.mark.parametrize("streams", [None, ("trades",), ("trades", "no_such_kind")])
@pytest.mark.parametrize("depth", [None, 200, 7, True, "500"])
def test_setting_rule_names_the_field_the_policy_check_refuses(streams: Any, depth: Any) -> None:
    """The route's `rc.setting_rule` and the policy's `_check_settings` name the same field."""
    try:
        policy._check_settings(streams, depth)
    except RecorderInvalidUpdateError as exc:
        named = "depth" if str(exc).startswith("depth") else "streams"
        assert rc.setting_rule(depth)[1] == named
    else:
        assert streams is None or "no_such_kind" not in streams


async def test_a_re_add_naming_the_retention_days_the_row_has_still_records_the_request() -> None:
    """As PUT and PATCH do: the record stands for the request, not for a change of value."""
    fake = FakeRecorder()
    fake.put("BTCUSDT", retention_days=7)
    env = _Env(fake, *W, elevated=True)
    assert (await env.add(symbol="BTCUSDT", retention_days=7)).status_code == 200
    route = env.audit[0][1]
    assert env.actions() == ["retention.change"]
    assert (route["before_state"], route["after_state"]) == (
        {"retention_days": 7}, {"retention_days": 7})  # fmt: skip


@pytest.mark.parametrize(
    ("extra", "actions"),
    [({"retention_days": 7}, ["retention.change", "recorder.start"]),
     ({"pinned": False, "retention_days": None}, ["retention.change", "recorder.start"]),
     ({"pinned": True, "retention_days": 7}, ["recorder.start", "retention.change"])],
)  # fmt: skip
async def test_an_add_naming_retention_days_records_it_ahead_as_put_and_patch_do(
    extra: Any, actions: list[str]
) -> None:
    """The route's own `retention.change` unless a pin (the policy's record) names it."""
    env = _Env(None, *W, elevated=True)
    env.caller, env.fail_audit = dataclasses.replace(env.caller, request_id=uuid.uuid4()), True
    refused = await env.add(symbol="SOLUSDT", **extra)
    assert (refused.status_code, env.fake.entries) == (503, {})
    env.fail_audit = False
    assert (await env.add(symbol="SOLUSDT", **extra)).status_code == 201
    assert env.actions() == actions
    if actions[0] == "retention.change":
        route = env.audit[0][1]
        assert (route["before_state"], route["after_state"]) == (
            {"retention_days": None}, {"retention_days": extra["retention_days"]})  # fmt: skip
        assert route["request_id"] == env.caller.request_id
