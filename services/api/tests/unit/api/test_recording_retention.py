"""#492 S4: `GET` and `PUT /recording/retention-policies`, over a bare app. The PUT replaces the
whole set; the Q5 mapping refuses what the store cannot hold (422 `retention_invalid_policy`) and
the validator a derived stream outliving `trades`; unknown fields are refused. `retention.change`
is written first, with the set before and after: if it cannot be, 503 and nothing stored. A key
replays; `apply_now` starts exactly one `retention_sweep` job (409 while one runs, 409 with the
scheduler off, nothing stored)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, get_args

import httpx
import pytest
from fastapi import FastAPI

from candleviewer.api import recording_retention as retention
from candleviewer.api.recorder_admin import JOB_KIND, AdminJobStore, Job
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome
from candleviewer.recorder.retention import RunReport

_PATH = "/recording/retention-policies"
_T = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


class _Store:
    """The policy rows; `log` keeps the order of audit and store calls."""

    def __init__(self, log: list[str]) -> None:
        self.rows: list[dict[str, Any]] = []
        self.log, self.replaced = log, 0
        self.actors: list[str | None] = []
        self.entered, self.hold = asyncio.Event(), None  # `hold`: park a replace until set
        self.fail: Exception | None = None  # raised by a replace, after it was asked for

    def seed(self, stream: str, days: int, action: str = "archive_parquet",
             symbol: str | None = None) -> None:  # fmt: skip
        self.rows.append({"id": str(uuid.uuid4()), "scope": "symbol" if symbol else "default",
                          "symbol": symbol, "stream": stream, "retain_days": days,
                          "action": action, "updated_at": _T})  # fmt: skip

    async def list_policies(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rows]

    async def replace(self, rows: list[dict[str, Any]], *,
                      actor: str | None) -> list[dict[str, Any]]:  # fmt: skip
        self.log.append("replace")
        self.entered.set()
        if self.hold is not None:
            await self.hold.wait()
        if self.fail is not None:
            raise self.fail
        self.replaced += 1
        self.actors.append(actor)
        self.rows = []
        for r in rows:
            self.seed(r["stream"], r["retain_days"], r["action"], r["symbol"])
        return await self.list_policies()


class _Sweeper:
    def __init__(self) -> None:
        self.runs, self.locked = 0, False

    async def run_nightly(self) -> RunReport:
        self.runs += 1  # a pass that found the volume lock held returns no `next_run_us`
        return RunReport(dry_run=False, next_run_us=None if self.locked else 1)


class _Env:
    def __init__(self, *perms: str, owner: bool = True, enabled: bool = True) -> None:
        self.caller = AuditPrincipal(uuid.uuid4(), "u", frozenset(perms), is_owner=owner)
        self.log: list[str] = []
        self.audit: list[tuple[str, dict[str, Any]]] = []
        self.audit_down = False
        self.store: _Store | None = _Store(self.log)
        self.jobs, self.sweeper = AdminJobStore(), _Sweeper()
        self.sweeper_up = True
        app = FastAPI()
        app.include_router(retention.make_recording_retention_router(
            lambda: self.store, self.jobs, lambda: self.sweeper if self.sweeper_up else None,
            enabled, self, self))  # fmt: skip
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def resolve(self, request: Any) -> AuditPrincipal | None:
        return self.caller if self.caller.permissions else None

    async def emit(self, action: str, **kwargs: Any) -> None:
        if action == "retention.change" and self.audit_down:
            raise RuntimeError("audit writer stopped")
        self.log.append(action)
        self.audit.append((action, kwargs))

    async def put(self, items: Any, key: str | None = None, *, whole: bool = True,
                  **params: Any) -> httpx.Response:  # fmt: skip
        """`whole`: add a default row for each stream the set leaves out."""
        headers = {} if key is None else {"Idempotency-Key": key}
        sent = _whole(items) if whole else items
        return await self.http.put(_PATH, json={"items": sent}, params=params, headers=headers)


def _item(stream: str = "trades", days: int = 30, **extra: Any) -> dict[str, Any]:
    return {"stream": stream, "retain_days": days, "action": "archive_parquet"} | extra


def _whole(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`items` plus a default archive row for every stream that has no default row in it."""
    have = {i["stream"] for i in items if i.get("symbol") is None}
    return items + [_item(s, 30) for s in get_args(retention.Stream) if s not in have]


def _set(body: Any) -> list[tuple[Any, ...]]:
    return [(i["stream"], i["retain_days"], i["action"], i["symbol"]) for i in body["items"]]


async def test_get_lists_the_set() -> None:
    env = _Env("recording:read")
    assert (await env.http.get(_PATH)).json() == {"items": []}
    assert env.store is not None
    env.store.seed("orderbook_delta", 3, "drop", "ETHUSDT")
    item = (await env.http.get(_PATH)).json()["items"][0]
    assert item | {"id": "x"} == {"id": "x", "stream": "orderbook_delta", "retain_days": 3,
                                  "action": "drop", "symbol": "ETHUSDT",
                                  "applies_to_pinned": False,
                                  "updated_at": "2026-10-23T12:00:00Z"}  # fmt: skip


async def test_put_replaces_the_set_after_writing_the_change_with_before_and_after() -> None:
    env = _Env("recording:write")
    assert env.store is not None
    env.store.seed("trades", 30)
    new = [_item(days=60), _item("orderbook_delta", 3, action="drop", symbol="ETHUSDT")]
    resp = await env.put(new)
    assert resp.status_code == 200
    assert _set(resp.json())[:2] == [("trades", 60, "archive_parquet", None),
                                     ("orderbook_delta", 3, "drop", "ETHUSDT")]  # fmt: skip
    assert env.log == ["retention.change", "replace"]
    change = env.audit[0][1]
    was = {"stream": "trades", "retain_days": 30, "action": "archive_parquet", "symbol": None}
    assert change["before_state"]["items"] == [was]
    assert [i["retain_days"] for i in change["after_state"]["items"]][:2] == [60, 3]
    assert change["actor_user_id"] == env.caller.user_id
    assert env.store.actors == [str(env.caller.user_id)]  # the stored rows' created_by


async def test_an_audit_that_cannot_be_written_stores_nothing() -> None:
    env = _Env("recording:write")
    env.audit_down = True
    resp = await env.put([_item()])
    assert (resp.status_code, resp.json()["code"]) == (503, "audit_unavailable")
    assert env.store is not None and env.store.replaced == 0


_REFUSED = {"downsample": [_item(action="downsample")], "pin": [_item(action="pin")]}
_REFUSED |= {"applies_to_pinned": [_item(applies_to_pinned=True)]}
_REFUSED |= {"duplicate": [_item(), _item(days=40)]}
_REFUSED |= {"derived-outlives-trades": [_item(action="drop", days=30)]}


@pytest.mark.parametrize("items", list(_REFUSED.values()), ids=list(_REFUSED))
async def test_a_set_the_store_cannot_hold_is_refused(items: list[dict[str, Any]]) -> None:
    env = _Env("recording:write")
    resp = await env.put(items)
    assert (resp.status_code, resp.json()["code"]) == (422, "retention_invalid_policy")
    assert env.log == []


_INVALID: list[Any] = [{"items": [_item(archive_path="x")]}, {"items": [_item(days=0)]}]
_INVALID += [{"items": "all"}, {"items": [], "extra": 1}, {"items": [_item(stream="bars")]}, {}]


@pytest.mark.parametrize("body", _INVALID)
async def test_an_invalid_body_or_unknown_field_is_422_validation_failed(body: Any) -> None:
    env = _Env("recording:write")
    resp = await env.http.put(_PATH, json=body)
    assert (resp.status_code, resp.json()["code"]) == (422, "validation_failed")
    assert env.log == []


async def test_a_key_replays_its_answer_and_refuses_another_body() -> None:
    env = _Env("recording:write")
    key = str(uuid.uuid4())
    first = await env.put([_item()], key)
    again = await env.put([_item()], key)
    assert again.content == first.content and again.headers["idempotency-replayed"] == "true"
    assert env.store is not None and env.store.replaced == 1
    other = await env.put([_item(days=9)], key)
    assert (other.status_code, other.json()["code"]) == (409, "idempotency_key_reuse")
    bad = await env.put([_item()], "not-a-uuid")
    assert (bad.status_code, bad.json()["code"]) == (422, "validation_failed")


async def _settle(jobs: AdminJobStore) -> list[Job]:
    await asyncio.gather(*jobs._tasks.values(), return_exceptions=True)
    return list(jobs._jobs.values())


async def test_apply_now_starts_exactly_one_sweep() -> None:
    env = _Env("recording:write")
    assert (await env.put([_item()], apply_now="true")).status_code == 200
    done = await _settle(env.jobs)
    assert [(j.kind, j.status) for j in done] == [(JOB_KIND, "succeeded")]
    assert env.sweeper.runs == 1


async def test_apply_now_while_a_sweep_runs_is_409_and_stores_nothing() -> None:
    env = _Env("recording:write")
    held = asyncio.Event()

    async def work(progress: Any) -> dict[str, object]:
        await held.wait()
        return {}

    async def done(job: Job) -> None:
        return None

    env.jobs.submit(JOB_KIND, ("x", "k", "h"), work, done)
    resp = await env.put([_item()], apply_now="true")
    assert (resp.status_code, resp.json()["code"]) == (409, "job_running")
    held.set()
    assert len(await _settle(env.jobs)) == 1 and env.log == [] and env.sweeper.runs == 0


async def test_apply_now_with_retention_off_is_409_and_stores_nothing() -> None:
    env = _Env("recording:write", enabled=False)
    resp = await env.put([_item()], apply_now="true")
    assert (resp.status_code, resp.json()["code"]) == (409, "conflict")
    assert env.log == [] and not env.jobs._jobs
    assert (await env.put([_item()])).status_code == 200  # without apply_now it is stored


async def test_a_refused_audit_leaves_no_sweep_running() -> None:
    env = _Env("recording:write")
    env.audit_down = True
    assert (await env.put([_item()], apply_now="true")).status_code == 503
    assert [j.status for j in await _settle(env.jobs)] == ["cancelled"]
    assert env.sweeper.runs == 0


async def test_no_session_401_and_no_permission_403_audited() -> None:
    assert (await _Env().put([_item()])).status_code == 401
    viewer = _Env("recording:read", owner=False)
    resp = await viewer.put([_item()])
    assert (resp.status_code, resp.json()["code"]) == (403, "forbidden")
    assert [a for a, _ in viewer.audit] == ["rbac.denied"]
    assert viewer.store is not None and viewer.store.replaced == 0
    assert (await _Env("marketdata:read").http.get(_PATH)).status_code == 403


async def test_a_manager_with_the_write_permission_replaces_the_set() -> None:
    assert (await _Env("recording:write", owner=False).put([_item()])).status_code == 200


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_no_store_is_503(method: str) -> None:
    env = _Env("recording:read", "recording:write")
    env.store = None
    resp = await env.http.request(method, _PATH, json={"items": _whole([])})
    assert (resp.status_code, resp.json()["code"]) == (503, "store_unavailable")


async def _park(env: _Env, key: str, days: int) -> asyncio.Task[httpx.Response]:
    return asyncio.create_task(env.put([_item(days=days)], key))


async def _spin() -> None:
    for _ in range(30):  # let every ready task run to its next wait
        await asyncio.sleep(0)


async def test_two_overlapping_puts_are_audited_in_the_order_they_are_stored() -> None:
    env = _Env("recording:write")
    assert env.store is not None
    env.store.seed("trades", 30)
    env.store.hold = asyncio.Event()
    first = await _park(env, str(uuid.uuid4()), 60)
    await env.store.entered.wait()  # the first is inside the replace
    second = await _park(env, str(uuid.uuid4()), 90)
    await _spin()
    env.store.hold.set()
    assert [r.status_code for r in await asyncio.gather(first, second)] == [200, 200]
    one, two = (kw for _, kw in env.audit)
    assert two["before_state"]["items"] == one["after_state"]["items"]
    assert two["after_state"]["items"][0]["retain_days"] == 90
    assert env.store.rows[0]["retain_days"] == 90  # the last record is the store


async def test_a_replace_that_fails_after_the_record_writes_a_failure_record_and_raises() -> None:
    env = _Env("recording:write")
    assert env.store is not None
    env.store.fail = RuntimeError("replace failed")
    with pytest.raises(RuntimeError, match="replace failed"):
        await env.put([_item()], apply_now="true")
    assert [a for a, _ in env.audit] == ["retention.change", "retention.change"]
    opened, closed = env.audit[0][1], env.audit[1][1]
    assert "outcome" not in opened and closed["outcome"] == AuditOutcome.FAILURE
    assert closed["reason"] == "RuntimeError" and closed["before_state"] == opened["before_state"]
    assert [j.status for j in await _settle(env.jobs)] == ["cancelled"]  # no sweep ran
    assert env.sweeper.runs == 0


async def test_a_body_declared_over_the_cap_is_refused_before_it_is_read() -> None:
    env = _Env("recording:write")
    read: list[bool] = []

    async def body() -> Any:
        read.append(True)
        yield b"{}"

    request = env.http.build_request("PUT", _PATH, content=body(),
                                     headers={"Content-Length": str(300 * 1024)})  # fmt: skip
    resp = await env.http.send(request)
    assert (resp.status_code, resp.json()["code"]) == (422, "validation_failed")
    assert read == [] and env.log == []


async def test_a_body_that_streams_past_the_cap_is_422() -> None:
    env = _Env("recording:write")
    big = b'{"items": [], "note": "' + b"x" * (300 * 1024) + b'"}'
    resp = await env.http.put(_PATH, content=big)
    assert (resp.status_code, resp.json()["code"]) == (422, "validation_failed")
    assert env.log == []


async def test_an_apply_now_that_is_not_true_or_false_is_422_and_stores_nothing() -> None:
    env = _Env("recording:write")
    resp = await env.put([_item()], apply_now="maybe")
    assert (resp.status_code, resp.json()["code"]) == (422, "validation_failed")
    assert env.log == [] and not env.jobs._jobs


async def test_apply_now_without_a_sweeper_is_503_and_stores_nothing() -> None:
    env = _Env("recording:write")
    env.sweeper_up = False
    resp = await env.put([_item()], apply_now="true")
    assert (resp.status_code, resp.json()["code"]) == (503, "store_unavailable")
    assert env.log == [] and not env.jobs._jobs
    assert (await env.put([_item()])).status_code == 200  # a plain replace needs no sweeper


@pytest.mark.parametrize("locked", [False, True])
async def test_the_sweep_result_says_when_the_volume_lock_was_held(locked: bool) -> None:
    env = _Env("recording:write")
    env.sweeper.locked = locked
    assert (await env.put([_item()], apply_now="true")).status_code == 200
    (job,) = await _settle(env.jobs)
    assert job.result is not None and job.result["skipped_locked"] is locked


async def test_a_set_that_omits_a_streams_default_row_is_refused_and_stores_nothing() -> None:
    streams = get_args(retention.Stream)
    for left_out in (streams[0], streams[-1], "klines"):
        env = _Env("recording:write")
        items = [_item(s, 30) for s in streams if s != left_out]
        resp = await env.put(items, whole=False)
        assert (resp.status_code, resp.json()["code"]) == (422, "retention_invalid_policy")
        assert env.log == [] and env.store is not None and env.store.replaced == 0
    # a symbol row does not stand in for the default row
    env = _Env("recording:write")
    items = [_item(s, 30) for s in streams if s != "klines"] + [
        _item("klines", 30, symbol="ETHUSDT")
    ]
    assert (await env.put(items, whole=False)).status_code == 422
    assert (await env.put([], whole=False)).status_code == 422  # an empty set omits them all
    assert (await env.put(_whole([]), whole=False)).status_code == 200


async def test_two_overlapping_puts_with_one_key_store_once_and_record_once() -> None:
    env = _Env("recording:write")
    assert env.store is not None
    env.store.hold = asyncio.Event()
    key = str(uuid.uuid4())
    first = await _park(env, key, 60)
    await env.store.entered.wait()  # the first is inside the replace
    second = await _park(env, key, 60)
    await _spin()
    env.store.hold.set()
    one, two = await asyncio.gather(first, second)
    assert (one.status_code, two.status_code) == (200, 200) and one.content == two.content
    assert two.headers["idempotency-replayed"] == "true"
    assert env.store.replaced == 1 and env.log == ["retention.change", "replace"]


async def test_a_chunked_body_with_no_length_over_the_cap_is_refused() -> None:
    env = _Env("recording:write")

    async def body() -> Any:
        yield b'{"items": [], "note": "'
        for _ in range(40):  # 40 KiB chunks: the cap is 256 KiB
            yield b"x" * 1024 * 40
        yield b'"}'

    request = env.http.build_request("PUT", _PATH, content=body())
    assert "content-length" not in request.headers
    resp = await env.http.send(request)
    assert (resp.status_code, resp.json()["code"]) == (422, "validation_failed")
    assert env.log == []


async def test_a_body_of_more_than_1000_items_is_refused() -> None:
    env = _Env("recording:write")
    many = [_item(symbol=f"A{n:04d}USDT") for n in range(1001)]
    resp = await env.http.put(_PATH, json={"items": many})
    assert (resp.status_code, resp.json()["code"]) == (422, "validation_failed")
    assert env.log == []
