"""E14-T01 /drawings: the #357 Gherkin scenarios by name (batch and index shape: C3b, #2384)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from _drawings_api_env import DRAWING_KEYS, SID, TRENDLINE, USER_A, USER_B, Env, wire

from candleviewer.api.drawings import _declared_length

PTS = TRENDLINE["geometry"]["points"]


@pytest.fixture
def env() -> Env:
    return Env()


def test_round_trip_persistence_per_user_and_symbol(env: Env) -> None:
    created = env.create()
    (got,) = env.listed("BTCUSDT")
    assert got == created and set(got) == DRAWING_KEYS  # no internal column leaks
    assert got["geometry"] == TRENDLINE["geometry"]  # identical decimals, never via float
    assert got["geometry"]["points"][1]["p"] == "63000.000000000001"
    assert uuid.UUID(got["id"]).version == 7 and got["owner_user_id"] == str(USER_A)
    assert got["updated_at"] == "2026-10-14T12:00:00.000001Z"
    assert env.listed("ETHUSDT") == []
    env.user = USER_B
    assert env.listed("BTCUSDT") == []


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_cross_user_access_is_denied_not_merely_filtered(env: Env, method: str) -> None:
    mine = env.create()
    rows_before = dict(env.repo.rows)
    env.user = USER_B
    body = wire(TRENDLINE) if method == "PUT" else None
    probe = env.c.request(method, f"/drawings/{mine['id']}", json=body)
    missing = env.c.request(method, f"/drawings/{uuid.uuid4()}", json=body)
    assert (probe.status_code, probe.json()) == (404, missing.json())  # not 403: no oracle
    assert env.repo.rows == rows_before and not env.repo.deleted  # row unchanged
    (denied,) = env.audit.denied()  # the probe is audited, the missing id is not
    assert {k: denied[k] for k in ("object_kind", "object_id", "outcome", "reason")} == {
        "object_kind": "drawing", "object_id": mine["id"], "outcome": "denied",
        "reason": "not_owner:workspaces:write:self"}  # fmt: skip
    assert denied["actor_user_id"] == USER_B and denied["severity"] == "warning"
    assert (denied["session_id"], denied["actor_ip"]) == (SID, "10.0.0.9")  # from the session


@pytest.mark.parametrize(("change", "field", "rule"), [
    ({"geometry": {"points": PTS[:1]}}, "geometry.points", "tool_point_count"),
    ({"tool": "scribble"}, "tool", "literal_error")])  # fmt: skip
def test_malformed_geometry_is_rejected(
    env: Env, change: dict[str, Any], field: str, rule: str
) -> None:
    r = env.c.post("/drawings", json=TRENDLINE | change)
    assert r.status_code == 422 and r.headers["content-type"] == "application/problem+json"
    assert r.json()["code"] == "validation_failed"
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [(field, rule)]
    assert env.repo.rows == {}  # nothing persisted


def test_deletes_are_soft_and_recoverable_within_retention(env: Env) -> None:
    d = env.create()
    assert env.c.delete(f"/drawings/{d['id']}").status_code == 204
    assert env.listed() == []
    assert d["id"] in env.repo.rows and d["id"] in env.repo.deleted  # kept until the purge job
    assert env.c.delete(f"/drawings/{d['id']}").status_code == 404
    assert env.audit.denied() == []  # one's own deleted drawing is not a cross-owner probe


@pytest.mark.parametrize("raw", ["²", "9" * 4301, "", "-1", " 12", "1e3", "١٢"])
def test_unusable_content_length_leaves_only_the_streaming_cap(raw: str) -> None:
    assert _declared_length(raw) is None and _declared_length("65537") == 65537  # never a 500
