"""#492 S7 and S8: `POST /recording/symbols`, `PUT …/{id}/pin`, `PATCH` and `DELETE …/{id}` over a
bare app, the fake control behind them. RBAC first (403 with `rbac.denied`, AC5), a user actor, the
body's size (413), the key and body (422), a malformed id (404), the per-user write limit (429), the
store (503), the `recorder` step-up where a write changes retention, a replay, the entry in the
settings' env (404), then the write, which the policy records ahead of the store. A non-Owner reads
every answer through the restricted view, and a refused stop by restricted refusal parity."""

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
from candleviewer.api.step_up_challenge import ChallengeText
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.recorder import control as rc
from candleviewer.recorder import policy
from candleviewer.recorder.errors import RecorderInvalidUpdateError, RecorderSymbolNotRecordedError
from candleviewer.recorder.models import Actor
from candleviewer.recorder.sessions import DEFAULT_STREAMS
from tests.unit.recorder._control_fakes import NOW, STREAMS, FakeRecorder

W = ("recording:read", "recording:write")
_ADD, _PIN = "/recording/symbols", "/recording/symbols/{}/pin"


def _one(entry_id: str) -> str:
    return f"/recording/symbols/{entry_id}"


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
        self.asked: list[ChallengeText | None] = []  # each step-up the routes demanded
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

    async def elevate(
        self, session_id: uuid.UUID | None, text: ChallengeText | None = None
    ) -> JSONResponse | None:
        self.asked.append(text)
        summary = None if text is None else text.action_summary
        refused = {"code": "step_up_required", "action_class": "recorder", "status": 403,
                   "action_summary": summary}  # fmt: skip
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
    await env.add(symbol="ETHUSDT", retention_days=7)  # no row: the policy records no retention
    assert [(a, r.get("outcome"), r.get("reason")) for a, r in env.audit] == [
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


async def test_past_the_limit_a_malformed_request_is_422_and_spends_no_budget() -> None:
    # #4868: the limit is admitted after the key, the body, the query and the path id parse, so
    # a request that is no write answers its 422 (or 404) and the 429 countdown stays for writes
    fake = FakeRecorder()
    entry = fake.put("ETHUSDT")
    env = _Env(fake, *W)
    for _ in range(30):
        assert (await env.add(symbol="BTCUSDT")).status_code in {200, 201}
    one = f"{_ADD}/{entry.id}"
    malformed = [
        await env.http.post(_ADD, json={"symbol": "BTCUSDT", "streams": ["trades AND 1=1 -- "]}),
        await env.http.post(_ADD, json={"symbol": "BTCUSDT"}, headers={"Idempotency-Key": "x"}),
        await env.http.put(_PIN.format(entry.id), json={"pinned": "false' OR '1'='1"}),
        await env.http.patch(one, json={"depth": "202-2"}),
        await env.http.delete(one, params={"force": "false ASC -- "}),
    ]
    assert [m.status_code for m in malformed] == [422] * 5
    assert {m.json()["code"] for m in malformed} == {"validation_failed"}
    bad_ids = ["{recordedSymbolId} AND 1=1 -- ", "00000000-0000-4000-8000-0000000000ff OR 1=1"]
    for bad in bad_ids:
        assert (await env.http.delete(f"{_ADD}/{bad}")).status_code == 404
        assert (await env.http.patch(f"{_ADD}/{bad}", json={"depth": 200})).status_code == 404
    limited = await env.add(symbol="BTCUSDT")  # the 31st well-formed write: still limited
    assert (limited.status_code, limited.json()["retry_after_seconds"]) == (429, 60)
    assert fake.entries.keys() == {"ETHUSDT", "BTCUSDT"}


async def test_a_body_over_the_cap_is_413_before_any_parse_or_the_limit() -> None:
    env = _Env(None, *W)
    big = b'{"symbol": "BTCUSDT", "pad": "' + b"x" * writes.MAX_WRITE_BODY_BYTES + b'"}'
    for _ in range(31):  # past the limit too: the cap answers first, and spends nothing
        refused = await env.http.post(_ADD, content=big)
        assert (refused.status_code, refused.json()["code"]) == (413, "payload_too_large")
    assert env.fake.entries == {} and env.actions() == []
    assert (await env.add(symbol="BTCUSDT")).status_code == 201


async def test_the_429_detail_is_one_sentence_and_the_countdown_rides_its_own_fields() -> None:
    # #4868: differential scanners compare bodies; the number is in Retry-After and the extension
    env = _Env(None, *W)
    for _ in range(30):
        await env.add(symbol="BTCUSDT")
    early = await env.add(symbol="BTCUSDT")
    env.now = 30.0
    later = await env.add(symbol="BTCUSDT")
    assert early.json()["detail"] == later.json()["detail"]
    assert (early.headers["Retry-After"], later.headers["Retry-After"]) == ("60", "30")


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
    """ETHUSDT: `retention_days` with no pin change, which the policy records (#2188 S3c)."""
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
    after = [(a, r["before_state"], r["after_state"]["retention_days"]) for a, r in env.audit]
    assert after == [("retention.change", {"retention_days": "9"}, "7")]
    unpinned = await env.http.put(_PIN.format(entry.id), json=days)
    assert (unpinned.json()["pinned"], unpinned.json()["retention_days"]) == (False, 7)
    assert "BTCUSDT" not in fake.entries  # an idle row unpinned goes


class _Gone(FakeRecorder):
    """The row goes between the lookup and the pin: the policy finds no active row."""

    async def set_pin(self, symbol: str, pinned: bool, actor: Any, *, restricted: bool,
                      retention_days: int | None = None) -> None:  # fmt: skip
        self.entries.clear()
        await super().set_pin(symbol, pinned, actor, restricted=restricted)  # no active row


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


_WRITES_BY_ID = [
    ("PUT", "/pin", {"pinned": True}),
    ("PATCH", "", {"depth": 50}),
    ("DELETE", "", None),
]


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
    for method, suffix, body in _WRITES_BY_ID:  # every write by id: the hidden row is no row
        answer = await env.http.request(method, f"{_one(hidden.id)}{suffix}", json=body)
        assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
    assert fake.entries["XRPUSDT"] == hidden and env.actions() == []


class _Spied(FakeRecorder):
    """Keeps every spec the route hands the port's `add`, as the real port will forward it."""

    def __init__(self) -> None:
        super().__init__()
        self.specs: list[rc.EntrySpec] = []

    async def add(self, symbol: str, spec: rc.EntrySpec, actor: Any, *, restricted: bool) -> Any:
        self.specs.append(spec)
        return await super().add(symbol, spec, actor, restricted=restricted)


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


async def test_an_add_naming_retention_days_the_policy_refuses_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`RecorderInvalidUpdateError` refuses before the policy records anything, the retention
    too (#2188 S3c: the policy, not the route, records it): `422`, no record."""
    monkeypatch.setattr(policy, "STREAM_KINDS", frozenset({"trades"}))
    env = _Env(None, *W, elevated=True)
    refused = await env.add(symbol="SOLUSDT", streams=["tickers"], retention_days=7)
    assert (refused.status_code, refused.json()["code"]) == (422, "validation_failed")
    assert refused.json()["errors"][0]["rule"] == "stream_names" and env.fake.entries == {}
    assert env.audit == []


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


async def test_a_re_add_naming_the_retention_days_the_row_has_records_nothing() -> None:
    """One record per write, the policy's: a re-add that changes nothing writes none."""
    fake = FakeRecorder()
    fake.put("BTCUSDT", retention_days=7)
    env = _Env(fake, *W, elevated=True)
    assert (await env.add(symbol="BTCUSDT", retention_days=7)).status_code == 200
    assert env.actions() == []


@pytest.mark.parametrize(
    ("extra", "actions"),
    [({"retention_days": 7}, ["recorder.start", "retention.change"]),
     ({"pinned": False, "retention_days": None}, ["recorder.start"]),
     ({"pinned": True, "retention_days": 7}, ["recorder.start", "retention.change"])],
)  # fmt: skip
async def test_an_add_naming_retention_days_has_the_policy_record_it_after_the_add(
    extra: Any, actions: list[str]
) -> None:
    """The policy records the add, then the pin or the retention (#2188 S3c), each ahead of its
    store; the route writes none of its own. A default already held changes and records none."""
    env = _Env(None, *W, elevated=True)
    env.caller, env.fail_audit = dataclasses.replace(env.caller, request_id=uuid.uuid4()), True
    refused = await env.add(symbol="SOLUSDT", **extra)
    assert (refused.status_code, env.fake.entries) == (503, {})
    env.fail_audit = False
    assert (await env.add(symbol="SOLUSDT", **extra)).status_code == 201
    assert env.actions() == actions


# -- S8: PATCH and DELETE ---------------------------------------------------------------------


async def test_a_stop_answers_204_and_the_row_then_lingers_until_the_grace_ends() -> None:
    """Q1: the manual reason ends at once; the row reads `lingering` with `linger_until`."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT")
    env = _Env(fake, *W)
    key = {"Idempotency-Key": str(uuid.uuid4())}
    stopped, again = [await env.http.delete(_one(entry.id), headers=key) for _ in range(2)]
    assert (stopped.status_code, stopped.content, again.status_code) == (204, b"", 204)
    row = (await env.http.get(_one(entry.id))).json()
    assert (row["lingering"], row["linger_until"]) == (True, "2026-10-23T12:30:00Z")
    assert env.actions() == ["recorder.stop"]  # the policy's record; the route writes none
    assert (env.audit[0][1]["object_id"], env.audit[0][1]["outcome"]) == ("BTCUSDT", "success")


async def test_a_stop_is_recorded_ahead_and_a_refused_record_stops_nothing() -> None:
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT")
    env = _Env(fake, *W)
    env.fail_audit = True
    refused = await env.http.delete(_one(entry.id))
    assert (refused.status_code, refused.json()["code"]) == (503, "audit_unavailable")
    assert fake.entries["BTCUSDT"] == entry and not fake.entries["BTCUSDT"].lingering


async def test_a_pinned_stop_keeps_its_pin_and_lists_as_stopped_after_the_grace() -> None:
    """Q4: a stop never drops the pin; the row stays, `stopped` and pinned."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", pinned=True)
    env = _Env(fake, *W)
    assert (await env.http.delete(_one(entry.id))).status_code == 204
    fake.lapse("BTCUSDT")
    row = (await env.http.get(_one(entry.id))).json()
    assert (row["state"], row["pinned"]) == ("stopped", True)


@pytest.mark.parametrize(
    ("query", "rule"),
    [("purge_data=true", "use_purge_route"), ("purge_data=1", "use_purge_route"),
     ("force=maybe", "bool_parsing")],
)  # fmt: skip
async def test_purge_data_on_a_stop_is_refused_with_use_purge_route(query: str, rule: str) -> None:
    """Q3: `purgeRecordedData` is the one path that deletes recorded data."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT")
    env = _Env(fake, *W)
    refused = await env.http.delete(f"{_one(entry.id)}?{query}")
    assert (refused.status_code, refused.json()["code"]) == (422, "validation_failed")
    assert refused.json()["errors"][0]["rule"] == rule
    assert fake.entries["BTCUSDT"] == entry and env.actions() == []
    assert (await env.http.delete(f"{_one(entry.id)}?purge_data=false")).status_code == 204


async def test_a_live_trigger_refuses_the_stop_with_409_and_force_ends_the_manual_reason() -> None:
    fake = FakeRecorder()
    entry = fake.put("ETHUSDT", "manual", "chart_open", refusals=("chart_open",))
    env = _Env(fake, *W)
    refused = await env.http.delete(_one(entry.id))
    assert (refused.status_code, refused.json()["code"], refused.json()["refusal"]) == (
        409, "conflict", "chart_open")  # fmt: skip
    assert fake.entries["ETHUSDT"].reasons == ("manual", "chart_open")
    forced = await env.http.delete(_one(entry.id), params={"force": "true"})
    assert forced.status_code == 204 and fake.entries["ETHUSDT"].reasons == ("chart_open",)
    assert env.actions() == ["recorder.stop", "recorder.stop"]  # the refusal, then the policy's
    assert [record["outcome"] for _, record in env.audit] == ["denied", "success"]


async def test_a_refused_stop_whose_record_cannot_be_written_is_503() -> None:
    fake = FakeRecorder()
    entry = fake.put("ETHUSDT", "manual", "chart_open", refusals=("chart_open",))
    env = _Env(fake, *W)
    env.fail_audit = True
    refused = await env.http.delete(_one(entry.id))
    assert (refused.status_code, refused.json()["code"]) == (503, "audit_unavailable")
    assert fake.entries["ETHUSDT"] == entry


async def test_a_key_first_used_without_force_is_409_with_it_or_on_another_id() -> None:
    """The fingerprint covers the method, the path with its query, and the body."""
    fake = FakeRecorder()
    first, other = fake.put("BTCUSDT"), fake.put("ETHUSDT")
    env = _Env(fake, *W)
    key = {"Idempotency-Key": str(uuid.uuid4())}
    assert (await env.http.delete(_one(first.id), headers=key)).status_code == 204
    for path, params in ((_one(first.id), {"force": "true"}), (_one(other.id), {})):
        reused = await env.http.delete(path, params=params, headers=key)
        assert (reused.status_code, reused.json()["code"]) == (409, "idempotency_key_reuse")
    assert "manual" in fake.entries["ETHUSDT"].reasons and env.actions() == ["recorder.stop"]


class _Counted(FakeRecorder):
    """Counts the lookups the routes make."""

    def __init__(self) -> None:
        super().__init__()
        self.looked_up: list[str] = []

    async def get(self, entry_id: str) -> Any:
        self.looked_up.append(entry_id)
        return await super().get(entry_id)


@pytest.mark.parametrize(("method", "suffix", "body"), _WRITES_BY_ID)
async def test_a_malformed_id_never_reaches_the_lookup(method: str, suffix: str, body: Any) -> None:
    fake = _Counted()
    env = _Env(fake, *W, elevated=True)
    answer = await env.http.request(method, f"/recording/symbols/not-a-uuid{suffix}", json=body)
    assert (answer.status_code, fake.looked_up, env.actions()) == (404, [], [])


class _Racing(FakeRecorder):
    """A trigger arrives between the lookup and the stop: the port refuses what the route saw
    no cause for."""

    async def get(self, entry_id: str) -> Any:
        found = await super().get(entry_id)
        return None if found is None else dataclasses.replace(found, refusals=())


async def _refused_stop(
    kind: type[FakeRecorder], owner: bool, *causes: Any
) -> tuple[_Env, httpx.Response]:
    fake = kind()
    entry = fake.put("SOLUSDT", "manual", *causes, refusals=causes)
    env = _Env(fake, *W, owner=owner)
    return env, await env.http.delete(_one(entry.id))


@pytest.mark.parametrize("kind", [FakeRecorder, _Racing])
@pytest.mark.parametrize("visible", [(), ("chart_open",)])
async def test_restricted_refusal_parity(kind: type[FakeRecorder], visible: Any) -> None:
    """(a) A non-Owner's refused stop reads the same for every hidden cause (and as if none
    held), (b) the Owner's names the cause, (c) the audit row names it for both."""
    seen: set[bytes] = set()
    for cause in sorted(rc.HIDDEN_CAUSES):
        for owner in (True, False):
            env, answer = await _refused_stop(kind, owner, cause, *visible)
            assert (answer.status_code, answer.json()["code"]) == (409, "conflict")
            assert (env.audit[-1][1]["outcome"], env.audit[-1][1]["reason"]) == ("denied", cause)
            if owner:
                assert answer.json()["refusal"] == cause
            else:
                seen.add(answer.content)
    if visible:
        seen.add((await _refused_stop(kind, False, *visible))[1].content)
    assert len(seen) == 1
    assert not any(cause in seen.pop().decode() for cause in rc.HIDDEN_CAUSES)


async def test_the_refusal_reads_the_one_hidden_cause_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(d) The routes keep no table of their own: widening the one `recorder.control` holds (and
    the WS topic imports) changes what a refused stop names for a non-Owner."""
    assert not hasattr(writes, "HIDDEN_CAUSES")
    named = (await _refused_stop(FakeRecorder, False, "chart_open"))[1].json()
    monkeypatch.setattr(rc, "HIDDEN_CAUSES", rc.HIDDEN_CAUSES | {"chart_open"})
    unnamed = (await _refused_stop(FakeRecorder, False, "chart_open"))[1].json()
    assert (named["refusal"], "refusal" in unnamed) == ("chart_open", False)


async def test_patch_of_streams_and_depth_needs_no_step_up_and_is_audited_ahead() -> None:
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", streams=("trades",))
    env = _Env(fake, *W)
    patched = await env.http.patch(_one(entry.id), json={"streams": ["tickers"], "depth": 50})
    assert (patched.status_code, patched.json()["streams"], patched.json()["depth"]) == (
        200, ["tickers"], 50)  # fmt: skip
    record = env.audit[0][1]  # the policy's record (update_manual); the route writes none
    assert (env.actions(), record["before_state"]) == (
        ["recorder.update"], {"streams": "trades", "depth": "200"})  # fmt: skip
    after = {"symbol": "BTCUSDT", "reason": "manual", "actor": str(env.caller.user_id),
             "streams": "tickers", "depth": "50"}  # fmt: skip
    assert record["after_state"] == after
    env.fail_audit = True
    refused = await env.http.patch(_one(entry.id), json={"depth": 1})
    assert refused.status_code == 503 and fake.entries["BTCUSDT"].depth == 50


@pytest.mark.parametrize(
    ("body", "actions"),
    [({"pinned": True}, ["retention.change"]), ({"retention_days": 7}, ["retention.change"]),
     ({"pinned": True, "retention_days": 7}, ["retention.change"]),
     ({"depth": 1, "pinned": True}, ["recorder.update", "retention.change"])],
)  # fmt: skip
async def test_patch_of_pinned_or_retention_days_needs_the_recorder_step_up(
    body: Any, actions: list[str]
) -> None:
    """A retention change is recorded as `retention.change`: by the policy for a pin, by the
    route for `retention_days` alone (no policy member records it)."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT")
    env = _Env(fake, *W)
    refused = await env.http.patch(_one(entry.id), json=body)
    assert (refused.status_code, refused.json()["code"]) == (403, "step_up_required")
    assert fake.entries["BTCUSDT"] == entry and env.actions() == []
    env.elevated = True
    assert (await env.http.patch(_one(entry.id), json=body)).status_code == 200
    assert env.actions() == actions


async def test_patch_of_an_entry_without_manual_is_409_and_an_empty_one_is_422() -> None:
    fake = FakeRecorder()
    entry = fake.put("ETHUSDT", "chart_open")
    env = _Env(fake, *W)
    refused = await env.http.patch(_one(entry.id), json={"depth": 50})
    assert (refused.status_code, refused.json()["code"]) == (409, "conflict")
    assert (env.actions(), env.audit[-1][1]["outcome"], env.audit[-1][1]["reason"]) == (
        ["recorder.update"], "denied", "not_manual")  # fmt: skip
    assert fake.entries["ETHUSDT"].depth == 200
    for bad in ({}, {"depth": 7}, {"streams": []}, {"archive_path": "/x"}):
        assert (await env.http.patch(_one(entry.id), json=bad)).status_code == 422


async def test_a_change_the_policy_refuses_as_invalid_is_422_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The policy's own check (`RecorderInvalidUpdateError`), on PATCH and on an add."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", streams=("trades",))
    monkeypatch.setattr(policy, "STREAM_KINDS", frozenset({"trades"}))
    env = _Env(fake, *W)
    refused = await env.http.patch(_one(entry.id), json={"streams": ["tickers"]})
    assert (refused.status_code, refused.json()["code"]) == (422, "validation_failed")
    assert refused.json()["errors"][0] == {"field": "streams", "rule": "stream_names",
                                           "message": "Refused by the recorder."}  # fmt: skip
    added = await env.add(symbol="ETHUSDT", streams=["tickers"])
    assert (added.status_code, added.json()["code"]) == (422, "validation_failed")
    assert fake.entries == {"BTCUSDT": entry} and env.actions() == []


async def test_a_null_retention_days_without_an_unpin_is_422() -> None:
    """`null` restores the default only with `pinned: false`; alone it would change nothing."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", retention_days=9)
    env = _Env(fake, *W, elevated=True)
    for body in ({"retention_days": None}, {"retention_days": None, "depth": 50}):
        refused = await env.http.patch(_one(entry.id), json=body)
        assert refused.json()["errors"][0]["rule"] == "retention_days_null_needs_unpin"
    assert fake.entries["BTCUSDT"] == entry and env.actions() == []
    unpinned = await env.http.patch(_one(entry.id), json={"retention_days": None, "pinned": False})
    assert unpinned.status_code == 200


@pytest.mark.parametrize("days", [7, None])
async def test_patch_of_retention_days_with_an_unpin_that_changes_no_pin_is_recorded(
    days: int | None,
) -> None:
    """`retention_days` named while `pinned` is not true: the policy's `set_retention` records
    it ahead of its store (a refused record stores none); the route writes none of its own."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", retention_days=9)
    env = _Env(fake, *W, elevated=True)
    body = {"pinned": False, "retention_days": days}
    env.fail_audit = True
    refused = await env.http.patch(_one(entry.id), json=body)
    assert (refused.status_code, refused.json()["code"]) == (503, "audit_unavailable")
    assert fake.entries["BTCUSDT"] == entry
    env.fail_audit = False
    stored = await env.http.patch(_one(entry.id), json=body)
    assert (stored.status_code, stored.json()["retention_days"]) == (200, days)
    assert env.actions() == ["retention.change"]  # the pin is unchanged: the retention's only
    record = env.audit[0][1]
    assert (record["before_state"], record["after_state"]["retention_days"]) == (
        {"retention_days": "9"}, None if days is None else str(days))  # fmt: skip


async def test_a_refused_mixed_patch_records_only_the_refusal() -> None:
    fake = FakeRecorder()
    entry = fake.put("ETHUSDT", "chart_open")
    env = _Env(fake, *W, elevated=True)
    refused = await env.http.patch(_one(entry.id), json={"retention_days": 7, "depth": 50})
    assert (refused.status_code, refused.json()["code"]) == (409, "conflict")
    assert fake.entries["ETHUSDT"] == entry
    records = [(a, r.get("outcome"), r.get("reason")) for a, r in env.audit]
    assert records == [("recorder.update", "denied", "not_manual")]


# -- S9: the relax guard (ruled 05:10Z; #2188 S3c) --------------------------------------------

_RELAXES = [(_PIN, "put", {"pinned": False}), (_PIN, "put", {"pinned": False, "retention_days": 7}),
            ("/recording/symbols/{}", "patch", {"retention_days": 7}),
            ("/recording/symbols/{}", "patch", {"pinned": False}),
            (_ADD, "post", {"symbol": "BTCUSDT", "retention_days": 7})]  # fmt: skip


@pytest.mark.parametrize(("path", "method", "body"), _RELAXES)
@pytest.mark.parametrize("cause", sorted(rc.HIDDEN_CAUSES))
async def test_a_non_owner_unpin_or_lower_retention_of_a_row_a_hidden_cause_holds_is_403(
    path: str, method: str, body: dict[str, Any], cause: Any
) -> None:
    """Refused before any write, one denied `retention.change`; a request flag or header that
    claims the Owner's view widens nothing (the view is the principal's, C-12.4)."""
    fake = FakeRecorder()
    pinned = body.get("pinned") is False
    entry = fake.put("BTCUSDT", "manual", cause, pinned=pinned, retention_days=None if pinned
                     else 60)  # fmt: skip
    env = _Env(fake, *W, owner=False, elevated=True)
    url = path.format(entry.id)
    for flags in ({}, {"params": {"restricted": "false"}},
                  {"headers": {"X-Restricted": "false", "X-View-As": "owner"}}):  # fmt: skip
        refused = await env.http.request(method, url, json=body, **flags)
        assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
        assert (
            refused.json()["detail"] == "Only the owner can unpin this row or lower its retention."
        )
        assert cause not in refused.text
    assert fake.entries["BTCUSDT"] == entry
    assert [(a, r["outcome"], r["reason"]) for a, r in env.audit] == [
        ("retention.change", "denied", "relax_refused")] * 3  # fmt: skip
    assert {r["object_id"] for _, r in env.audit} == {entry.id}  # the port's check, before writes
    smuggled = await env.http.request(method, url, json=body | {"restricted": False})
    assert smuggled.status_code == 422  # no body field names the view
    owner = _Env(fake, *W, elevated=True)
    assert (await owner.http.request(method, url, json=body)).status_code == 200


async def test_a_relax_the_policy_refuses_after_the_ports_check_is_recorded_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The view changed between the port's check and the policy's: the policy's denied record
    is the only one, and the answer the same `403`."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", "manual", "position_open", pinned=True)
    answers = iter([True, False])
    monkeypatch.setattr(fake, "relax_allowed", lambda symbol, *, restricted: next(answers))
    env = _Env(fake, *W, owner=False, elevated=True)
    refused = await env.http.put(_PIN.format(entry.id), json={"pinned": False})
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    assert [(a, r["outcome"], r["actor_label"]) for a, r in env.audit] == [
        ("retention.change", "denied", f"user:{env.caller.actor_id}")]  # the policy's  # fmt: skip
    assert fake.entries["BTCUSDT"] == entry


class _Stopped(FakeRecorder):
    """A stop races the add: the row is gone when the port reads it back."""

    async def add(self, symbol: str, spec: rc.EntrySpec, actor: Any, *, restricted: bool) -> Any:
        raise RecorderSymbolNotRecordedError("the recorded row was removed")


async def test_an_add_whose_row_a_racing_stop_removed_is_404_audited_as_denied() -> None:
    env = _Env(_Stopped(), *W)
    gone = await env.add(symbol="BTCUSDT")
    assert (gone.status_code, gone.json()["code"]) == (404, "not_found")
    assert [(a, r["outcome"], r["reason"]) for a, r in env.audit] == [
        ("recorder.start", "denied", "not_recorded")]  # fmt: skip


@pytest.mark.parametrize("method", ["patch", "post"])
async def test_retention_days_on_a_pinned_row_without_an_unpin_is_ignored(method: str) -> None:
    """A pin keeps forever and nulls `retention_days` (22), so days named on a pinned row with no
    `pinned: false` change nothing: `200`, `retention_days` stays null, no record."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", pinned=True)
    env = _Env(fake, *W, elevated=True)
    url, body = ((_one(entry.id), {"retention_days": 7}) if method == "patch"
                 else (_ADD, {"symbol": "BTCUSDT", "retention_days": 7}))  # fmt: skip
    kept = await env.http.request(method, url, json=body)
    assert (kept.status_code, kept.json()["pinned"], kept.json()["retention_days"]) == (
        200, True, None)  # fmt: skip
    assert fake.entries["BTCUSDT"] == entry and env.actions() == []


class _StartRefused(FakeRecorder):
    """The status also lists a symbol whose start was refused and that has no row (no id)."""

    async def status(self) -> rc.ControlStatus:
        listed = await super().status()
        idle = rc.RecordedEntry("", "SOLUSDT", ("position_open",), "idle",
                                refusals=("symbol_cap",))  # fmt: skip
        return dataclasses.replace(listed, entries=(*listed.entries, idle))


async def test_an_add_of_a_start_refused_symbol_with_no_row_is_a_fresh_add() -> None:
    """A status-only entry is no row: no join (a non-Owner would get 503 for its missing
    streams), a plain add that creates the row."""
    fake = _StartRefused()
    env = _Env(fake, *W, owner=False)
    added = await env.add(symbol="SOLUSDT")
    assert (added.status_code, added.json()["reason"]) == (201, "manual")
    assert fake.entries["SOLUSDT"].streams == STREAMS


async def test_a_pin_nulls_the_rows_retention_and_the_answers_show_null() -> None:
    """A pin nulls the stored days (#2188 S3c); the answers show `retention_days: null`."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", retention_days=60)
    env = _Env(fake, *W, elevated=True)
    pinned = await env.http.put(_PIN.format(entry.id), json={"pinned": True})
    assert (pinned.json()["pinned"], pinned.json()["retention_days"]) == (True, None)
    assert fake.entries["BTCUSDT"].retention_days is None  # the pin nulled it
    assert (await env.http.get(_one(entry.id))).json()["retention_days"] is None


@pytest.mark.parametrize(("days", "status"), [(7, 403), (60, 200)])
async def test_a_non_owner_retention_change_on_a_null_row_reads_null_as_the_default(
    days: int, status: int
) -> None:
    """21 §3.6.1: an unpinned NULL keeps the default (30 days), so NULL -> 7 lowers and is
    refused where a hidden cause holds the row; NULL -> 60 raises it and passes."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", "manual", "position_open")
    env = _Env(fake, *W, owner=False, elevated=True)
    answer = await env.http.patch(_one(entry.id), json={"retention_days": days})
    assert answer.status_code == status
    assert fake.entries["BTCUSDT"].retention_days == (None if status == 403 else days)


async def test_a_patch_of_retention_on_a_pinned_row_is_ignored_and_records_nothing() -> None:
    """A pinned row keeps forever: no retention write, no record, `retention_days: null`."""
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", pinned=True, retention_days=60)  # a number left on a pinned row
    env = _Env(fake, *W, elevated=True)
    kept = await env.http.patch(_one(entry.id), json={"retention_days": 7})
    assert (kept.status_code, kept.json()["retention_days"]) == (200, None)
    assert fake.entries["BTCUSDT"].retention_days == 60 and env.actions() == []


# -- #2304 slice 3c: the pin's `recorder` step-up comes after the body and the entry's lookup ----


@pytest.mark.parametrize(
    "body",
    [{}, {"pinned": "yes"}, {"pinned": True, "x": 1}, {"pinned": False, "retention_days": 0}],
)
async def test_an_unelevated_callers_invalid_pin_is_the_422_never_a_challenge(body: Any) -> None:
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT")
    env = _Env(fake, *W)
    refused = await env.http.put(_PIN.format(entry.id), json=body)
    assert (refused.status_code, refused.json()["code"]) == (422, "validation_failed")
    assert env.asked == [] and not fake.entries["BTCUSDT"].pinned


async def test_an_unelevated_viewers_pin_is_the_audited_403_never_a_challenge() -> None:
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT")
    env = _Env(fake, "recording:read", owner=False)
    refused = await env.http.put(_PIN.format(entry.id), json={"pinned": True})
    assert (refused.status_code, refused.json()["code"]) == (403, "forbidden")
    assert env.actions() == ["rbac.denied"] and env.asked == []


@pytest.mark.parametrize("entry_id", [str(uuid.UUID(int=1)), "not-a-uuid"])
async def test_an_unelevated_callers_pin_of_a_missing_entry_is_the_404_never_a_challenge(
    entry_id: str,
) -> None:
    env = _Env(FakeRecorder(), *W)
    refused = await env.http.put(_PIN.format(entry_id), json={"pinned": True})
    assert (refused.status_code, refused.json()["code"]) == (404, "not_found")
    assert env.asked == [] and env.actions() == []


@pytest.mark.parametrize(
    ("body", "summary"),
    [
        ({"pinned": True, "retention_days": 9}, "Pin the recording of BTCUSDT (keep forever)"),
        ({"pinned": False, "retention_days": 7}, "Unpin the recording of BTCUSDT, keeping 7 days"),
        ({"pinned": False}, "Unpin the recording of BTCUSDT"),
    ],
    ids=["pin", "unpin-days", "unpin"],
)
async def test_an_unelevated_callers_pin_is_challenged_restating_the_entry(
    body: Any, summary: str
) -> None:
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT", pinned=not body["pinned"])
    env = _Env(fake, *W)
    refused = await env.http.put(_PIN.format(entry.id), json=body)
    assert (refused.status_code, refused.json()["code"]) == (403, "step_up_required")
    assert refused.json()["action_summary"] == summary
    assert fake.entries["BTCUSDT"] == entry and env.actions() == []


async def test_a_kept_pin_is_read_back_only_behind_a_live_window() -> None:
    fake, key = FakeRecorder(), {"Idempotency-Key": str(uuid.uuid4())}
    entry = fake.put("BTCUSDT")
    env = _Env(fake, *W, elevated=True)
    first = await env.http.put(_PIN.format(entry.id), json={"pinned": True}, headers=key)
    assert first.status_code == 200 and env.actions() == ["retention.change"]
    env.elevated = False  # the window ended
    again = await env.http.put(_PIN.format(entry.id), json={"pinned": True}, headers=key)
    assert (again.status_code, again.json()["code"]) == (403, "step_up_required")
    assert "idempotency-replayed" not in again.headers
    env.elevated = True
    replayed = await env.http.put(_PIN.format(entry.id), json={"pinned": True}, headers=key)
    assert (replayed.content, replayed.headers["idempotency-replayed"]) == (first.content, "true")
    assert env.actions() == ["retention.change"]  # recorded once


async def test_an_unelevated_callers_key_reused_for_another_pin_is_challenged_not_409() -> None:
    """The key's lookup comes after the gate, as on the retention set: without a live window a
    reused key with another body meets the challenge, never `409 idempotency_key_reuse`; with
    one, the 409."""
    fake, key = FakeRecorder(), {"Idempotency-Key": str(uuid.uuid4())}
    entry = fake.put("BTCUSDT")
    env = _Env(fake, *W, elevated=True)
    first = await env.http.put(_PIN.format(entry.id), json={"pinned": True}, headers=key)
    assert first.status_code == 200
    env.elevated = False
    other = await env.http.put(_PIN.format(entry.id), json={"pinned": False}, headers=key)
    assert (other.status_code, other.json()["code"]) == (403, "step_up_required")
    assert other.json()["action_summary"] == "Unpin the recording of BTCUSDT"
    env.elevated = True
    reused = await env.http.put(_PIN.format(entry.id), json={"pinned": False}, headers=key)
    assert (reused.status_code, reused.json()["code"]) == (409, "idempotency_key_reuse")
    assert fake.entries["BTCUSDT"].pinned and env.actions() == ["retention.change"]


async def test_a_pin_wired_without_its_step_up_fails_closed() -> None:
    fake = FakeRecorder()
    entry = fake.put("BTCUSDT")
    env = _Env(fake, *W, elevated=True)
    app = FastAPI()
    app.include_router(writes.make_recording_writes_router(
        lambda: fake, env, env, None, env.listed.__contains__))  # fmt: skip
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    refused = await http.put(_PIN.format(entry.id), json={"pinned": True})
    assert refused.status_code == 503 and not fake.entries["BTCUSDT"].pinned
