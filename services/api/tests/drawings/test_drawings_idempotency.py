"""E14-T01 Idempotency-Key on POST /drawings and POST /drawings/batch (decision record 8): the
bounded per-user cache, replay of the stored 2xx, `409 idempotency_key_reuse`, isolation, and a
replay never bypassing authentication or RBAC."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call

import pytest
from _drawings_api_env import BATCH, TRENDLINE, USER_B, Env, wire

from candleviewer.api.drawings import (
    IDEMPOTENCY_ENTRY_OVERHEAD,
    IDEMPOTENCY_MAX_BYTES,
    IDEMPOTENCY_MAX_ENTRIES,
    IDEMPOTENCY_MAX_ENTRY_BYTES,
    IDEMPOTENCY_TTL_S,
    IDEMPOTENCY_USER_MAX_BYTES,
    IDEMPOTENCY_USER_MAX_ENTRIES,
    IdempotencyCache,
    StoredResponse,
)

KEY = "4d9f1c2e-8a7b-4c3d-9e1f-0a1b2c3d4e5f"
H = {"Idempotency-Key": KEY}
BIG = b"x" * IDEMPOTENCY_MAX_ENTRY_BYTES  # the largest storable body (one shared buffer)


def _stored(body: bytes = b"{}") -> StoredResponse:
    return StoredResponse("digest", 201, body, None)


def _bodies(path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(body, another body) for `path`, built lazily (generated models: needs #2380)."""
    if path == "/drawings":
        return wire(TRENDLINE), wire(TRENDLINE | {"label": "x"})
    one = wire({"operations": [{"op": "create", "drawing": TRENDLINE}]}, BATCH)
    return one, {"operations": one["operations"] * 2}


def test_limits_are_the_review_values() -> None:
    limits = (IDEMPOTENCY_MAX_ENTRIES, IDEMPOTENCY_MAX_BYTES, IDEMPOTENCY_USER_MAX_ENTRIES,
              IDEMPOTENCY_USER_MAX_BYTES, IDEMPOTENCY_MAX_ENTRY_BYTES,
              IDEMPOTENCY_TTL_S)  # fmt: skip
    assert limits == (4096, 32 * 2**20, 256, 4 * 2**20, 256 * 2**10, 86_400)


def test_global_bytes_evict_the_least_recently_used_entry() -> None:
    cache = IdempotencyCache()
    for user in range(9):  # 9 users x 15 maximal entries: each under 4 MiB, together over 32 MiB
        for k in range(15):
            cache.put(f"u{user}", f"k{k}", _stored(BIG))
    assert cache.stored_bytes <= IDEMPOTENCY_MAX_BYTES and len(cache) < 9 * 15
    assert cache.get("u0", "k0") is None and cache.get("u8", "k14") is not None


def test_one_user_filling_its_quota_never_evicts_another() -> None:
    cache = IdempotencyCache()
    cache.put("b", "k", _stored())
    for k in range(IDEMPOTENCY_USER_MAX_ENTRIES + 50):  # A over its entry cap...
        cache.put("a", f"k{k}", _stored())
    for k in range(20):  # ...then over its byte cap
        cache.put("a", f"big{k}", _stored(BIG))
    assert cache.get("b", "k") is not None  # B untouched: the global caps still hold
    assert cache.get("a", "k0") is None and cache.get("a", "big19") is not None
    b_size = len(b"{}") + len("k") + IDEMPOTENCY_ENTRY_OVERHEAD
    assert cache.stored_bytes - b_size <= IDEMPOTENCY_USER_MAX_BYTES


def test_a_hit_refreshes_recency_within_the_user() -> None:
    cache = IdempotencyCache()
    for k in range(IDEMPOTENCY_USER_MAX_ENTRIES):
        cache.put("a", f"k{k}", _stored())
    assert cache.get("a", "k0") is not None  # k0 becomes the most recent
    cache.put("a", "new", _stored())  # over the cap: the oldest (k1) goes, not k0
    assert cache.get("a", "k0") is not None and cache.get("a", "k1") is None


def test_a_second_store_under_one_key_replaces_without_double_counting() -> None:
    cache = IdempotencyCache()  # e.g. two concurrent first requests with the same key
    cache.put("a", "k", _stored(b"first"))
    cache.put("a", "k", _stored(b"second!"))
    assert cache.get("a", "k") == _stored(b"second!") and len(cache) == 1
    assert cache.stored_bytes == len(b"second!") + len("k") + IDEMPOTENCY_ENTRY_OVERHEAD


def test_an_oversize_body_is_never_stored() -> None:
    cache = IdempotencyCache()
    cache.put("a", "k", _stored(BIG + b"x"))
    assert cache.get("a", "k") is None and len(cache) == cache.stored_bytes == 0


def test_entries_expire_after_the_ttl_on_the_monotonic_clock() -> None:
    now = [1000.0]
    cache = IdempotencyCache(clock=lambda: now[0])
    cache.put("a", "k", _stored())
    now[0] += IDEMPOTENCY_TTL_S - 1  # 86_399 s later: a hit
    assert cache.get("a", "k") is not None
    now[0] += 2  # 86_401 s: an expired hit is a miss, and is dropped
    assert cache.get("a", "k") is None and len(cache) == cache.stored_bytes == 0


@pytest.mark.parametrize(("path", "status"), [("/drawings", 201), ("/drawings/batch", 200)])
def test_same_key_and_body_replays_the_stored_response(path: str, status: int) -> None:
    env, body = Env(), _bodies(path)[0]
    first = env.c.post(path, json=body, headers=H)
    again = env.c.post(path, json=body, headers={"Idempotency-Key": KEY.upper()})
    assert first.status_code == again.status_code == status
    assert again.content == first.content and again.headers["idempotency-replayed"] == "true"
    assert "idempotency-replayed" not in first.headers
    assert again.headers.get("etag") == first.headers.get("etag")
    assert len(env.repo.rows) == 1  # applied once


@pytest.mark.parametrize("path", ["/drawings", "/drawings/batch"])
def test_same_key_with_another_body_is_409_reuse(path: str) -> None:
    metrics = MagicMock()
    env, (body, other) = Env(metrics=metrics), _bodies(path)
    assert env.c.post(path, json=body, headers=H).status_code < 300
    r = env.c.post(path, json=other, headers=H)
    assert r.status_code == 409 and r.json()["code"] == "idempotency_key_reuse"
    assert len(env.repo.rows) == 1
    assert metrics.conflicts.labels.call_args_list == [call("idempotency_key_reuse")]


def test_keys_are_scoped_per_user_and_operation_and_only_successes_are_kept() -> None:
    env = Env()
    bad = env.c.post("/drawings", json=TRENDLINE | {"tool": "x"}, headers=H)
    assert bad.status_code == 422  # a failure is never remembered...
    one, batch = _bodies("/drawings")[0], _bodies("/drawings/batch")[0]
    assert env.c.post("/drawings", json=one, headers=H).status_code == 201
    assert env.c.post("/drawings/batch", json=batch, headers=H).status_code == 200  # own scope
    env.user = USER_B  # ...and another user's identical key is a different request
    r = env.c.post("/drawings", json=one, headers=H)
    assert r.status_code == 201 and "idempotency-replayed" not in r.headers
    assert len(env.repo.rows) == 3


def test_malformed_idempotency_key_is_422() -> None:
    env = Env()
    r = env.c.post("/drawings", json=_bodies("/drawings")[0], headers={"Idempotency-Key": "x"})
    assert r.status_code == 422
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
        ("Idempotency-Key", "uuid_parsing")
    ]
    assert env.repo.rows == {}


def test_an_oversize_response_is_not_stored_so_a_retry_runs_again() -> None:
    env = Env(idempotency=IdempotencyCache(max_entry_bytes=64))  # every response is "oversize"
    body = _bodies("/drawings")[0]
    first = env.c.post("/drawings", json=body, headers=H)
    again = env.c.post("/drawings", json=body, headers=H)
    assert (first.status_code, again.status_code) == (201, 201)
    assert first.json()["id"] != again.json()["id"] and "idempotency-replayed" not in again.headers


def test_a_replay_never_bypasses_authentication_or_rbac() -> None:
    env, body = Env(), _bodies("/drawings")[0]
    assert env.c.post("/drawings", json=body, headers=H).status_code == 201
    env.grants = {"workspaces:read"}  # downgraded after the first call
    denied = env.c.post("/drawings", json=body, headers=H)
    assert denied.status_code == 403 and "idempotency-replayed" not in denied.headers
    env.user = None  # the session is gone
    gone = env.c.post("/drawings", json=body, headers=H)
    assert gone.status_code == 401 and "idempotency-replayed" not in gone.headers
    assert len(env.repo.rows) == 1
