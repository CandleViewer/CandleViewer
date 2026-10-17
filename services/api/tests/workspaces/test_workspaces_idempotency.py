"""E15-T01 D23 (#402): Idempotency-Key replay on POST/DELETE /workspaces* through the shared LRU
(`api/idempotency.py`, ruling Q5), in D13's order: every 422 first, then the replay or a 409
`idempotency_key_reuse`, then the 404; the fingerprint is method + path + body and only 2xx
outcomes are kept."""

from __future__ import annotations

import uuid

import _workspaces_api_env as fakes
import pytest
from _workspaces_api_env import LAYOUT, USER_B, Env, wire
from fastapi.testclient import TestClient

import candleviewer.app as appmod
from tests.csrf_helpers import arm_csrf
from tests.drawings._drawings_api_env import TRENDLINE, FakeDrawingRepo
from tests.drawings._drawings_api_env import wire as drawing_wire
from tests.unit.auth.auth_fakes import FullUsers


@pytest.fixture
def env() -> Env:
    return Env()


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def _called(env: Env, name: str) -> int:
    return [n for n, _ in env.repo.calls].count(name)


def test_a_retried_create_replays_the_stored_201(env: Env) -> None:
    key, body = _key(), wire({"name": "Scalping"})
    first, again = (env.c.post("/workspaces", json=body, headers=key) for _ in range(2))
    assert (first.status_code, again.status_code) == (201, 201)
    assert again.content == first.content and again.headers["etag"] == first.headers["etag"]
    assert again.headers["idempotency-replayed"] == "true"
    assert "idempotency-replayed" not in first.headers and _called(env, "create_workspace") == 1


def test_a_retried_delete_replays_its_204_rather_than_a_404(env: Env) -> None:
    env.create("Keep")
    url, key = f"/workspaces/{env.create('Gone')['id']}", _key()
    first, again = (env.c.delete(url, headers=key) for _ in range(2))
    assert (first.status_code, again.status_code) == (204, 204) and again.content == b""
    assert again.headers["idempotency-replayed"] == "true" and "content-type" not in again.headers
    assert env.c.delete(url).status_code == 404  # without the key: the real outcome


def test_layout_create_and_delete_replay_too(env: Env) -> None:
    url, key = f"/workspaces/{env.create()['id']}/layouts", _key()
    body = wire(LAYOUT, "LayoutInput")
    made, again = (env.c.post(url, json=body, headers=key) for _ in range(2))
    assert made.status_code == 201 and again.content == made.content
    assert again.headers["idempotency-replayed"] == "true" and _called(env, "create_layout") == 1
    gone, key = f"{url}/{made.json()['id']}", _key()
    assert [env.c.delete(gone, headers=key).status_code for _ in range(2)] == [204, 204]
    assert _called(env, "soft_delete_layout") == 1


def test_the_key_with_another_body_or_path_is_a_409_and_writes_nothing(env: Env) -> None:
    key = _key()
    assert env.c.post("/workspaces", json=wire({"name": "A"}), headers=key).status_code == 201
    other = env.c.post("/workspaces", json=wire({"name": "B"}), headers=key)
    assert other.status_code == 409 and other.json()["code"] == "idempotency_key_reuse"
    b, c = env.create("C"), env.create("D")
    key = _key()
    assert env.c.delete(f"/workspaces/{b['id']}", headers=key).status_code == 204
    elsewhere = env.c.delete(f"/workspaces/{c['id']}", headers=key)  # D23: the path counts
    assert elsewhere.status_code == 409 and elsewhere.json()["code"] == "idempotency_key_reuse"
    assert c["id"] not in env.repo.deleted and _called(env, "create_workspace") == 3


def test_only_successes_are_kept_and_a_422_comes_before_the_replay(env: Env) -> None:
    env.create("Taken")
    key = _key()
    taken = env.c.post("/workspaces", json=wire({"name": "Taken"}), headers=key)
    assert taken.status_code == 409 and taken.json()["code"] == "conflict"  # not stored
    fresh = env.c.post("/workspaces", json=wire({"name": "Fresh"}), headers=key)
    assert fresh.status_code == 201 and "idempotency-replayed" not in fresh.headers
    invalid = env.c.post("/workspaces", json={"name": ""}, headers=key)
    assert invalid.status_code == 422  # validation precedes the replay step (D13)


def test_keys_are_scoped_per_user(env: Env) -> None:
    key, body = _key(), wire({"name": "Mine"})
    assert env.c.post("/workspaces", json=body, headers=key).status_code == 201
    theirs = env.as_user(USER_B).c.post("/workspaces", json=body, headers=key)
    assert theirs.status_code == 201 and "idempotency-replayed" not in theirs.headers


def test_a_key_stored_by_one_router_is_never_replayed_by_the_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through the real `create_app()`: /workspaces and /drawings keep their own caches and
    operationId-scoped keys, so one key sent to both runs both writes (no replay, no 409)."""
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _settings: fakes.Identity())
    app = appmod.create_app()
    app.state.app_context.auth._sessions = fakes.Sessions()
    app.state.app_context.auth._repository = FullUsers()  # #2295: classified as full
    writer = app.state.app_context.audit._writer = fakes.Audit()
    app.state.workspaces_repository = workspaces = fakes.FakeWorkspaceRepo()
    app.state.drawings_repository = drawings = FakeDrawingRepo()
    c = arm_csrf(TestClient(app, client=("127.0.0.1", 50000)), app.state.csrf_codec, fakes.SID)
    for n, order in enumerate((("/workspaces", "/drawings"), ("/drawings", "/workspaces"))):
        body = {"/workspaces": wire({"name": f"Charts {n}"}), "/drawings": drawing_wire(TRENDLINE)}
        h = {"Authorization": "Bearer tok-a", "Idempotency-Key": str(uuid.uuid4())}
        stored, other = (c.post(path, json=body[path], headers=h) for path in order)
        assert (stored.status_code, other.status_code) == (201, 201), other.text
        assert "idempotency-replayed" not in other.headers  # its own write, not the other's 201
        again = c.post(order[0], json=body[order[0]], headers=h)
        assert again.headers["idempotency-replayed"] == "true"  # the key was kept where sent
    assert (len(workspaces.rows), len(drawings.rows), writer.calls) == (2, 2, [])
