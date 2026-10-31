"""#2727 (SR-E14-05; E14 threat model DR32, DR33, RR4): the drawings quota and the write bucket.

The fake applies the repository's `quota_breach`, so these pin the router's answers and the rule's
boundaries; the SQL count and its lock are pinned in `tests/integration/storage/`.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.api.drawings_limiter import TRACKED_USERS, DrawingsWriteLimiter
from candleviewer.storage.repositories.drawings import (
    MAX_DRAWINGS_PER_SYMBOL,
    MAX_DRAWINGS_PER_USER,
    quota_breach,
)
from tests.drawings._drawings_api_env import BATCH, TRENDLINE, USER_A, USER_B, VIEWER, Env, wire


def _env(per_symbol: int = 500, per_user: int = 5000, burst: int = 20) -> Env:
    env = Env()
    env.repo.per_symbol, env.repo.per_user = per_symbol, per_user
    env.limiter = DrawingsWriteLimiter(burst=burst, clock=lambda: env.now)
    return env


def _post(env: Env, symbol: str = "BTCUSDT") -> int:
    return int(env.c.post("/drawings", json=wire(TRENDLINE | {"symbol": symbol})).status_code)


def _batch(env: Env, ops: list[dict[str, Any]]) -> Any:
    return env.c.post("/drawings/batch", json=wire({"operations": ops}, BATCH))


def test_the_limits_are_the_ruled_values() -> None:
    assert (MAX_DRAWINGS_PER_SYMBOL, MAX_DRAWINGS_PER_USER) == (500, 5000)
    w = DrawingsWriteLimiter(clock=lambda: 0.0)  # 60 a minute, burst 20
    assert [w.try_take("u") for _ in range(21)] == [None] * 20 + [1]


@pytest.mark.parametrize(("per_symbol", "per_user", "symbols"), [
    (3, 100, ["BTCUSDT"] * 3), (100, 3, ["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
])  # fmt: skip
def test_n_drawings_are_allowed_and_n_plus_one_is_409_writing_nothing(
    per_symbol: int, per_user: int, symbols: list[str]
) -> None:
    env = _env(per_symbol, per_user, burst=100)
    assert [_post(env, s) for s in symbols] == [201] * 3
    rows = dict(env.repo.rows)
    r = env.c.post("/drawings", json=wire(TRENDLINE))
    assert (r.status_code, r.json()["code"]) == (409, "drawings_quota_exceeded")
    assert r.headers["content-type"] == "application/problem+json" and env.repo.rows == rows
    assert _post(env, "XRPUSDT") == (201 if per_user > 3 else 409)


def test_another_users_rows_never_count_against_the_caller() -> None:
    env = _env(per_symbol=2, per_user=2)
    env.user = USER_B
    assert [_post(env) for _ in range(3)] == [201, 201, 409]
    env.user = USER_A
    assert [_post(env) for _ in range(3)] == [201, 201, 409]


def test_a_batch_counts_creates_net_of_deletes_and_rolls_back_past_the_quota() -> None:
    env = _env(per_symbol=2)
    first, _ = env.create(), env.create()
    before = (dict(env.repo.rows), dict(env.repo.deleted))
    r = _batch(env, [{"op": "create", "drawing": TRENDLINE}])
    assert r.json()["code"] == "drawings_quota_exceeded" and r.status_code == 409
    assert (env.repo.rows, env.repo.deleted) == before
    delete = {"op": "delete", "id": first["id"], "if_match": first["updated_at"]}
    assert _batch(env, [delete, {"op": "create", "drawing": TRENDLINE}]).status_code == 200


def test_a_foreign_delete_in_a_batch_frees_no_quota_and_is_target_unavailable() -> None:
    env = _env(per_symbol=1)
    env.user = USER_B
    theirs = env.create()
    env.user = USER_A
    env.create()
    probe = {"op": "delete", "id": theirs["id"], "if_match": theirs["updated_at"]}
    r = _batch(env, [probe, {"op": "create", "drawing": TRENDLINE}])
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (409, "target_unavailable")
    assert theirs["id"] not in env.repo.deleted


def test_only_growth_is_refused_so_a_clean_up_over_the_quota_passes() -> None:
    live = {"BTCUSDT": 7}
    assert quota_breach(live, {"BTCUSDT": -1}, per_symbol=5, per_user=5) is None
    breach = quota_breach(live, {"ETHUSDT": 1}, per_symbol=5, per_user=5)
    assert breach is not None and (breach.scope, breach.limit) == ("user", 5)


def test_past_the_burst_is_429_with_retry_after_and_the_bucket_refills_on_the_clock() -> None:
    env = Env()
    assert [_post(env) for _ in range(20)] == [201] * 20
    rows = dict(env.repo.rows)
    r = env.c.post("/drawings", json=wire(TRENDLINE))
    assert (r.status_code, r.json()["code"], r.json()["retry_after_seconds"]) == (
        429, "rate_limited", 1)  # fmt: skip
    assert r.headers["Retry-After"] == "1" and env.repo.rows == rows
    env.now += 1.0
    assert [_post(env) for _ in range(2)] == [201, 429]
    env.now += 60.0  # refilled to the burst, never past it
    assert [_post(env) for _ in range(21)] == [201] * 20 + [429]
    env.user = USER_B  # one user's empty bucket never limits another
    assert _post(env) == 201


def test_put_delete_and_batch_take_tokens_and_reads_take_none() -> None:
    env = Env()
    url = f"/drawings/{env.create()['id']}"
    assert all(env.c.put(url, json=wire(TRENDLINE)).status_code == 200 for _ in range(9))
    assert all(_batch(env, [{"op": "create", "drawing": TRENDLINE}]).status_code == 200
               for _ in range(9))  # fmt: skip
    assert [env.c.delete(url).status_code for _ in range(2)] == [204, 429]  # the 20th, the 21st
    get = {"params": {"symbol": "BTCUSDT"}}
    assert all(env.c.get("/drawings", **get).status_code == 200 for _ in range(30))


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_a_forbidden_or_anonymous_write_is_refused_before_the_bucket(method: str) -> None:
    env = Env()
    made = env.create()["id"]
    url = "/drawings" if method == "post" else f"/drawings/{made}"
    body = {"json": wire(TRENDLINE)} if method != "delete" else {}
    env.user = VIEWER
    assert all(getattr(env.c, method)(url, **body).status_code == 403 for _ in range(25))
    env.user = None
    assert getattr(env.c, method)(url, **body).status_code == 401
    assert len(env.limiter) == 1  # the creator's bucket only: refusals took no token


def test_a_foreign_id_write_is_404_and_spends_only_the_callers_tokens() -> None:
    env = Env()
    env.user = USER_B
    theirs = f"/drawings/{env.create()['id']}"
    env.user = USER_A
    assert [env.c.delete(theirs).status_code for _ in range(21)] == [404] * 20 + [429]
    env.user = USER_B
    assert env.c.delete(theirs).status_code == 204


def test_the_limiter_is_bounded_and_validates_its_rates() -> None:
    w = DrawingsWriteLimiter(per_minute=6, burst=1, clock=lambda: 0.0)
    assert w.try_take("u") is None and w.try_take("u") == 10  # one token per 10 s
    for i in range(TRACKED_USERS + 5):
        w.try_take(f"user-{i}")
    assert len(w) == TRACKED_USERS
    for bad in ({"per_minute": 0}, {"burst": 0}):
        with pytest.raises(ValueError):
            DrawingsWriteLimiter(**bad)
