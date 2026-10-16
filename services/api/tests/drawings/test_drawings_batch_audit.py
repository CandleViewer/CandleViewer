"""E14-T01 batch cross-owner probes (#357 R3): an update/delete whose target is not the caller's,
another owner's or missing alike, is audited as `rbac.denied` like a foreign PUT/DELETE, and is the
very same 409 `target_unavailable` as the caller's own soft-deleted target. The caller's own rows
(deleted, stale token) are never audited."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, call

import pytest
from _drawings_api_env import BATCH, SID, TRENDLINE, USER_B, Env, wire
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.storage.repositories.drawings import BatchOpFailed

STALE = "2026-10-14T12:00:00.000000Z"
NOT_OWNER = "not_owner:workspaces:write:self"
KINDS = ["update", "delete"]
#: What a failed audit write leaves on the wire: the registered 503, or a bug's plain 500.
BODY = {503: '"code":"store_unavailable"', 500: "Internal Server Error"}


def _target(kind: str, d: dict[str, Any], **over: Any) -> dict[str, Any]:
    """An update or delete aimed at `d` (anything with `id` and `updated_at`)."""
    op = {"op": kind, "id": d["id"], "if_match": d["updated_at"]}
    return op | ({"drawing": TRENDLINE} if kind == "update" else {}) | over


def _ghost() -> dict[str, str]:
    return {"id": str(uuid.uuid4()), "updated_at": STALE}  # no such drawing, any owner


def _post(env: Env, *ops: dict[str, Any]) -> Any:
    return env.c.post("/drawings/batch", json=wire({"operations": list(ops)}, BATCH))


@pytest.mark.parametrize("kind", KINDS)
def test_a_foreign_target_is_409_and_audited_exactly_once(kind: str) -> None:
    env = Env()
    mine = env.create()  # user A's drawing
    before = dict(env.repo.rows)
    env.user = USER_B
    r = _post(env, {"op": "create", "drawing": TRENDLINE}, _target(kind, mine))
    assert r.status_code == 409 and r.json()["code"] == "conflict"
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
        ("operations.1", "target_unavailable")
    ]
    assert env.repo.rows == before and not env.repo.deleted  # rolled back, the create too
    (denied,) = env.audit.denied()
    fields = ("object_kind", "object_id", "outcome", "severity", "reason")
    assert {k: denied[k] for k in fields} == {
        "object_kind": "drawing", "object_id": mine["id"], "outcome": "denied",
        "severity": "warning", "reason": NOT_OWNER}  # fmt: skip
    assert (denied["actor_user_id"], denied["actor_label"]) == (USER_B, str(USER_B))
    assert (denied["session_id"], denied["actor_ip"]) == (SID, "10.0.0.9")  # from the session


def test_a_batch_probe_is_recorded_exactly_like_a_foreign_delete() -> None:
    env = Env()
    mine = env.create()
    env.user = USER_B
    assert env.c.delete(f"/drawings/{mine['id']}").status_code == 404
    assert _post(env, _target("delete", mine)).status_code == 409
    single, batch = env.audit.denied()
    assert batch == single  # same actor, session, request, object, outcome, severity and reason


@pytest.mark.parametrize("kind", KINDS)
def test_a_missing_target_is_audited_like_a_foreign_one(kind: str) -> None:
    env, ghost = Env(), _ghost()
    r = _post(env, _target(kind, ghost))
    assert r.status_code == 409 and r.json()["errors"][0]["rule"] == "target_unavailable"
    (denied,) = env.audit.denied()
    assert (denied["object_id"], denied["reason"]) == (ghost["id"], NOT_OWNER)


def test_only_the_failing_operation_of_a_batch_is_audited() -> None:
    env, first, second = Env(), _ghost(), _ghost()
    r = _post(env, _target("delete", first), _target("update", second))
    assert r.json()["errors"][0]["field"] == "operations.0"
    assert [c["object_id"] for c in env.audit.denied()] == [first["id"]]  # the batch stops there


@pytest.mark.parametrize("kind", KINDS)
def test_refusals_are_byte_identical_for_foreign_missing_and_own_deleted_targets(kind: str) -> None:
    env = Env()
    foreign = env.create()  # user A's, live
    env.user = USER_B
    gone = env.create()  # B's own, then soft-deleted
    assert env.c.delete(f"/drawings/{gone['id']}").status_code == 204
    replies = [_post(env, _target(kind, t)) for t in (foreign, _ghost(), gone)]
    assert {r.status_code for r in replies} == {409}
    assert len({(r.headers["content-type"], r.content) for r in replies}) == 1  # no oracle


@pytest.mark.parametrize("kind", KINDS)
def test_the_callers_own_deleted_target_is_409_but_not_audited(kind: str) -> None:
    env = Env()
    gone = env.create()
    assert env.c.delete(f"/drawings/{gone['id']}").status_code == 204
    r = _post(env, _target(kind, gone))
    assert r.status_code == 409 and r.json()["errors"][0]["rule"] == "target_unavailable"
    assert env.audit.denied() == []


@pytest.mark.parametrize("kind", KINDS)
def test_a_stale_token_on_the_callers_own_drawing_is_not_audited(kind: str) -> None:
    env = Env()
    mine = env.create()
    r = _post(env, _target(kind, mine, if_match=STALE))
    assert r.status_code == 409 and r.json()["errors"][0]["rule"] == "version_conflict"
    assert env.audit.denied() == []


def test_the_internal_rule_reaches_neither_the_metric_nor_the_log() -> None:
    metrics = MagicMock()  # C4's `DrawingsMetrics`: `rule` has a closed set of four values
    env = Env(metrics=metrics)
    mine = env.create()
    env.user = USER_B
    with capture_logs() as logs:
        assert _post(env, _target("delete", mine)).status_code == 409
    assert metrics.conflicts.labels.call_args_list == [call("target_unavailable")]
    assert [(e["event"], e["rule"]) for e in logs] == [
        ("drawings_batch_conflict", "target_unavailable")
    ]


def _refusing_emit(failure: Exception) -> Any:
    """An audit writer whose every `emit` raises `failure`."""

    async def down(action: str, **_kw: Any) -> None:
        raise failure

    return down


@pytest.mark.parametrize("route", ["put", "batch"])
@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (AuditUnavailable("audit store down"), 503),  # the WAL refused the record
        (AuditWriterStopped(), 503),  # the writer is not running
        (RuntimeError("audit store down"), 500),  # only an `AuditError` is the audit sink's: a bug
    ],  # stays a visible 500
    ids=["unavailable", "stopped", "unexpected"],
)
def test_a_failed_audit_write_fails_the_probe_closed(
    route: str, failure: Exception, status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = Env()
    mine = env.create()
    env.user = USER_B
    before = (dict(env.repo.rows), dict(env.repo.deleted))
    monkeypatch.setattr(env.audit, "emit", _refusing_emit(failure))
    client = TestClient(env.c.app, raise_server_exceptions=False)  # an unexpected error is a 500
    if route == "put":
        r = client.put(f"/drawings/{mine['id']}", json=wire(TRENDLINE))
    else:
        body = wire({"operations": [_target("delete", mine)]}, BATCH)
        r = client.post("/drawings/batch", json=body)
    assert r.status_code == status  # never the plain 404 / 409 that would hide the missing record
    assert BODY[status] in r.text  # the registered problem, or the server's own 500
    assert (dict(env.repo.rows), dict(env.repo.deleted)) == before  # no state changed


def test_a_failed_audit_write_still_counts_and_logs_the_batch_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SR-125, as `enforce()`: the conflict is counted and logged before the audit write."""
    metrics = MagicMock()
    env = Env(metrics=metrics)
    mine = env.create()
    env.user = USER_B
    monkeypatch.setattr(env.audit, "emit", _refusing_emit(AuditUnavailable("audit store down")))
    with capture_logs() as logs:
        assert _post(env, _target("delete", mine)).status_code == 503
    assert metrics.conflicts.labels.call_args_list == [call("target_unavailable")]
    conflicts = [(e["event"], e["rule"]) for e in logs if e["event"] == "drawings_batch_conflict"]
    assert conflicts == [("drawings_batch_conflict", "target_unavailable")]


def test_an_unexpected_audit_failure_never_chains_the_internal_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A traceback prints `__context__`: `target_not_owned` must not be in it (it is not wire)."""
    env = Env()
    mine = env.create()
    env.user = USER_B
    monkeypatch.setattr(env.audit, "emit", _refusing_emit(RuntimeError("audit store down")))
    with pytest.raises(RuntimeError) as err:  # the TestClient re-raises what the app leaves
        _post(env, _target("delete", mine))
    chain: list[BaseException] = []
    exc: BaseException | None = err.value
    while exc is not None:
        chain.append(exc)
        exc = exc.__context__
    assert not any(isinstance(e, BatchOpFailed) for e in chain)
