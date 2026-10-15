"""E14-X02 (#474) abuse cases, part A: stored XSS corpus and IDOR enumeration on /drawings.

Pins threat-model rows DR20/DR21 (IDOR), DR28 (cursor), DR25 (no echo) and DR39 (idempotency key
across users), plus the stored half of the XSS tabletop: hostile text is stored as inert JSON,
only `_STRIP` characters are removed, nothing is HTML-decoded or encoded. DR22 is not pinned here.
Rendering sinks (SR-E14-01..03: DOM, aria-label, SDF text) are unbuilt: residual RR6.
Router-level only (in-memory repository); the Postgres leg lives in `tests/contract/drawings`.
No `nosniff` header exists in the repo: the JSON content type is the only inertness signal
(finding for E14-X03).
Tripwire: `layout_id` is unknown today (no layouts table, every non-null value is refused); when
E15 makes layouts real (#402, RR2, SR-E14-09) add a same-owner foreign-layout case here."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _drawings_api_env import BATCH, TRENDLINE, USER_A, USER_B, Env, wire

CORPUS = json.loads(
    (Path(__file__).parents[1] / "fixtures/drawings_abuse/corpus.v1.json").read_text("utf-8")
)
assert CORPUS["version"] == 1
CASES = [pytest.param(c, id=c["id"]) for c in CORPUS["payloads"]]
LONG = [pytest.param(c, id=c["id"]) for c in CORPUS["payloads"] if len(c["payload"]) > 120]
TEXT = {"symbol": "BTCUSDT", "tool": "text", "style": {}}
PT = TRENDLINE["geometry"]["points"][0]
SEQUENTIAL = "00000000-0000-4000-8000-000000000001"  # id classes: counter-like and random-like
RANDOM = "9b2f6c1e-5d47-4a8e-b3c0-7e1d2a4f8c65"
KEY = "4d9f1c2e-8a7b-4c3d-9e1f-0a1b2c3d4e5f"
STALE = "2026-10-14T12:00:00.000000Z"
JSON_CT = "application/json"


def _text(payload: str, label: str | None = None) -> dict[str, Any]:
    d = TEXT | {"geometry": {"points": [PT], "text": payload}}
    return d | ({} if label is None else {"label": label})


def _label(c: dict[str, str]) -> str | None:
    return c["payload"] if len(c["payload"]) <= 120 else None


def _stored(env: Env, c: dict[str, str], path: str) -> Any:
    """Write the payload through a create or batch path; returns the response."""
    body = wire(_text(c["payload"], _label(c)))
    if path == "create":
        return env.c.post("/drawings", json=body)
    op: dict[str, Any] = {"op": "create", "drawing": _text(c["payload"], _label(c))}
    if path == "batch_update":
        d = env.create(tool="text", geometry={"points": [PT], "text": "x"}, style={})
        op = {"op": "update", "id": d["id"], "if_match": d["updated_at"], "drawing": op["drawing"]}
    return env.c.post("/drawings/batch", json=wire({"operations": [op]}, BATCH))


@pytest.mark.parametrize("path", ["create", "put", "batch_create", "batch_update"])
@pytest.mark.parametrize("case", CASES)
def test_corpus_is_stored_stripped_never_decoded_and_served_as_json(
    case: dict[str, str], path: str
) -> None:
    env = Env()
    if path == "put":  # a PUT must keep the tool: start from a text drawing
        d = env.create(tool="text", geometry={"points": [PT], "text": "x"}, style={})
        r = env.c.put(f"/drawings/{d['id']}", json=wire(_text(case["payload"], _label(case))))
        assert r.status_code == 200, r.text
    else:
        r = _stored(env, case, path)
        assert r.status_code in (200, 201), r.text
    assert r.headers["content-type"] == JSON_CT
    listing = env.c.get("/drawings", params={"symbol": "BTCUSDT"})
    assert listing.headers["content-type"] == JSON_CT  # inert on the read path too
    stored = [g for g in listing.json()["items"] if g["tool"] == "text"]
    assert [g["geometry"]["text"] for g in stored] == [case["text"]]
    assert [g.get("label") for g in stored] == [case["label"] if _label(case) else None]


@pytest.mark.parametrize("case", CASES)
def test_a_replayed_hostile_write_is_served_as_the_same_inert_json(case: dict[str, str]) -> None:
    env = Env()
    body = wire(_text(case["payload"], _label(case)))
    first = env.c.post("/drawings", json=body, headers={"Idempotency-Key": KEY})
    again = env.c.post("/drawings", json=body, headers={"Idempotency-Key": KEY})
    assert (
        again.headers["idempotency-replayed"] == "true" and again.headers["content-type"] == JSON_CT
    )
    assert again.content == first.content and again.json()["geometry"]["text"] == case["text"]


@pytest.mark.parametrize("case", LONG)
def test_a_label_over_the_raw_cap_is_string_too_long_with_no_echo(case: dict[str, str]) -> None:
    env = Env()
    r = env.c.post("/drawings", json=TRENDLINE | {"label": case["payload"]})
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/problem+json")
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [("label", "string_too_long")]
    assert case["payload"][:20] not in str(r.json())  # decoded comparison
    assert env.repo.rows == {}


ANCHORS = ["#5B8DEF;background:url(x)", "#5B8DEF\n", '#5B8DEF"onload=']
STYLE_INPUTS = [pytest.param(c["payload"], id=c["id"]) for c in CORPUS["payloads"]] + [
    pytest.param(a, id=f"anchor{i}") for i, a in enumerate(ANCHORS)
]


@pytest.mark.parametrize("key", ["colour", "fill_colour"])
@pytest.mark.parametrize(
    "payload",
    [pytest.param(c["payload"], id=c["id"]) for c in CORPUS["payloads"]]
    + [pytest.param(a, id=f"anchor{i}") for i, a in enumerate(ANCHORS)],
)
def test_style_colours_accept_only_a_bare_hex_colour(key: str, payload: str) -> None:
    env = Env()
    r = env.c.post("/drawings", json=TRENDLINE | {"style": {key: payload}})
    assert r.status_code == 422, r.text
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
        (f"style.{key}", "string_pattern_mismatch")
    ]
    assert payload[:20] not in str(r.json()) and env.repo.rows == {}


@pytest.mark.parametrize("ch", ["\U0001f680", "é", "م"], ids=["4byte", "combining", "rtl"])
def test_unicode_amplification_counts_code_points_at_both_caps(ch: str) -> None:
    env = Env()
    n = len(ch)  # a combining pair is 2 code points
    ok = env.c.post("/drawings", json=wire(_text(ch * (1000 // n), ch * (120 // n))))
    assert ok.status_code == 201 and ok.json()["geometry"]["text"] == ch * (1000 // n)
    text = env.c.post("/drawings", json=_text(ch * (1000 // n + 1)))
    assert [(e["field"], e["rule"]) for e in text.json()["errors"]] == [
        ("geometry.text", "string_too_long")
    ]
    label = env.c.post("/drawings", json=TRENDLINE | {"label": ch * (120 // n + 1)})
    assert [(e["field"], e["rule"]) for e in label.json()["errors"]] == [
        ("label", "string_too_long")
    ]
    assert len(env.repo.rows) == 1  # only the in-cap write


def test_a_lone_surrogate_is_refused_at_parse_and_nothing_is_persisted() -> None:
    env = Env()
    r = env.c.post("/drawings", content=json.dumps(_text("\ud800"), ensure_ascii=True))
    assert r.status_code == 422 and r.json()["errors"][0]["rule"] == "json_invalid"
    assert env.repo.rows == {} and env.repo.calls == []


def _victim(env: Env, kind: str) -> tuple[str, str]:
    """(id, updated_at token) of a foreign, soft-deleted or never-existing drawing."""
    if kind == "missing":
        return RANDOM, STALE
    d = env.create()  # user A's
    if kind == "deleted":
        env.c.delete(f"/drawings/{d['id']}")
        return d["id"], str(env.repo.rows[d["id"]].updated_at.isoformat().replace("+00:00", "Z"))
    return d["id"], d["updated_at"]


def _put(env: Env, did: str, **headers: str) -> Any:
    return env.c.put(f"/drawings/{did}", json=wire(TRENDLINE), headers=headers)


@pytest.mark.parametrize("kind", ["foreign", "deleted", "missing"])
def test_put_delete_probes_return_one_identical_404_body(kind: str) -> None:
    env = Env()
    did, token = _victim(env, kind)
    reference = Env()
    reference.user = USER_B
    ref = _put(reference, RANDOM).text
    env.user = USER_B
    sent = [{}, {"If-Match": token}, {"If-Match": f'"{token}"'}, {"If-Match": STALE}]
    attempts = [_put(env, did, **h) for h in sent]
    for r in attempts:
        assert r.status_code == 404 and r.text == ref, (kind, r.text)
    gone = env.c.delete(f"/drawings/{did}")
    assert gone.status_code == 404 and gone.json()["code"] == "not_found"


@pytest.mark.parametrize("value", ["*", "garbage", '"', "W/"])
def test_unusable_if_match_is_a_uniform_412_for_own_foreign_and_missing_ids(value: str) -> None:
    env = Env()
    mine = env.create()
    ids = {"own": mine["id"], "missing": RANDOM}
    env.user = USER_B
    ids["foreign"] = mine["id"]
    bodies = {k: _put(env, v, **{"If-Match": value}) for k, v in ids.items()}
    env.user = USER_A
    bodies["own"] = _put(env, mine["id"], **{"If-Match": value})
    assert {r.status_code for r in bodies.values()} == {412}
    assert len({r.text for r in bodies.values()}) == 1  # no own/foreign/missing oracle


@pytest.mark.parametrize("did", [SEQUENTIAL, RANDOM])
def test_enumerated_id_classes_are_404_for_every_method(did: str) -> None:
    env = Env()
    env.create()
    env.user = USER_B
    assert _put(env, did).status_code == 404
    assert env.c.delete(f"/drawings/{did}").status_code == 404
    assert env.repo.deleted == {}


@pytest.mark.parametrize("kind", ["foreign", "deleted", "missing"])
@pytest.mark.parametrize("verb", ["update", "delete"])
def test_a_batch_with_one_unavailable_target_rolls_back_the_attackers_own_ops(
    kind: str, verb: str
) -> None:
    env = Env()
    vid, vtoken = _victim(env, kind)
    env.user = USER_B
    own = [env.create(), env.create()]
    before, deleted = dict(env.repo.rows), dict(env.repo.deleted)
    foreign: dict[str, Any] = {"op": verb, "id": vid, "if_match": vtoken}
    if verb == "update":
        foreign["drawing"] = TRENDLINE | {"label": "pwned"}
    ops = [
        {"op": "update", "id": own[0]["id"], "if_match": own[0]["updated_at"],
         "drawing": TRENDLINE | {"label": "mine"}},
        {"op": "delete", "id": own[1]["id"], "if_match": own[1]["updated_at"]},
        foreign,
    ]  # fmt: skip
    r = env.c.post("/drawings/batch", json=wire({"operations": ops}, BATCH))
    assert r.status_code == 409, r.text
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
        ("operations.2", "target_unavailable")
    ]
    assert env.repo.rows == before and env.repo.deleted == deleted  # B's own earlier ops undone


def test_batch_bodies_are_identical_for_foreign_deleted_and_missing_targets() -> None:
    texts = set()
    for kind in ("foreign", "deleted", "missing"):
        env = Env()
        vid, token = _victim(env, kind)
        env.user = USER_B
        op = {"op": "delete", "id": vid, "if_match": token}
        r = env.c.post("/drawings/batch", json=wire({"operations": [op]}, BATCH))
        texts.add(r.text)
    assert len(texts) == 1  # full body, no per-class oracle


def test_a_cursor_minted_for_another_user_opens_nothing() -> None:
    """DR28: the cursor is an unsigned keyset position, not a capability."""
    env = Env()
    for _ in range(3):
        env.create()
    page = env.c.get("/drawings", params={"symbol": "BTCUSDT", "limit": "1"}).json()
    cursor = page["meta"]["next_cursor"]
    env.user = USER_B
    r = env.c.get("/drawings", params={"symbol": "BTCUSDT", "limit": "1", "cursor": cursor})
    assert r.status_code == 200 and r.json()["items"] == []
    assert page["items"][0]["id"] not in r.text


def test_a_second_users_reuse_of_the_same_key_and_body_is_a_409_without_the_first_response() -> (
    None
):
    """DR39: keys are scoped per user, so B's reuse is a different request, not a replay."""
    env = Env()
    body = wire(TRENDLINE | {"label": "owner secret level"})
    first = env.c.post("/drawings", json=body, headers={"Idempotency-Key": KEY})
    assert first.status_code == 201
    env.user = USER_B
    own = env.c.post("/drawings", json=wire(TRENDLINE | {"label": "mine"}),
                     headers={"Idempotency-Key": KEY})  # fmt: skip
    assert own.status_code == 201 and "owner secret level" not in own.text
    same = env.c.post("/drawings", json=body, headers={"Idempotency-Key": KEY})
    assert same.status_code == 409 and same.json()["code"] == "idempotency_key_reuse"
    assert first.json()["id"] not in same.text
