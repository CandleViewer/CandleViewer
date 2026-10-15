"""E14-X02 (#474) abuse cases, part A: stored XSS corpus and IDOR enumeration on /drawings.

Pins threat-model rows DR20/DR21/DR22 (IDOR) and the stored half of the XSS tabletop: the API
stores hostile text as inert JSON, strips only `_STRIP`, never HTML-decodes or encodes. Rendering
sinks (SR-E14-01..03: DOM, aria-label, SDF text) are unbuilt and stay residual (RR6)."""

from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any

import pytest
from _drawings_api_env import BATCH, TRENDLINE, USER_A, USER_B, Env, wire

CORPUS = json.loads(
    (Path(__file__).parents[1] / "fixtures/drawings_abuse/corpus.v1.json").read_text("utf-8")
)
assert CORPUS["version"] == 1
CASES = [pytest.param(c, id=c["id"]) for c in CORPUS["payloads"]]
TEXT = {"symbol": "BTCUSDT", "tool": "text", "style": {}}
PT = TRENDLINE["geometry"]["points"][0]
NOT_FOUND = {"drawing_not_found", "not_found"}


def _text(payload: str, label: str | None = None) -> dict[str, Any]:
    d = TEXT | {"geometry": {"points": [PT], "text": payload}}
    return d | ({} if label is None else {"label": label})


def _inert(r: Any) -> None:
    assert r.headers["content-type"] == "application/json"  # never html, never sniffable as one


@pytest.mark.parametrize("case", CASES)
def test_corpus_is_stored_as_inert_stripped_text_via_create_update_and_batch(
    case: dict[str, str],
) -> None:
    env = Env()
    label_ok = len(case["payload"]) <= 120
    label = case["payload"] if label_ok else None
    r = env.c.post("/drawings", json=wire(_text(case["payload"], label)))
    assert r.status_code == 201, r.text
    _inert(r)
    d = r.json()
    assert d["geometry"]["text"] == case["text"]  # stripped per `_STRIP`, never HTML-decoded
    assert d.get("label") == (case["label"] if label_ok else None)
    again = env.c.put(f"/drawings/{d['id']}", json=wire(_text(case["payload"], label)),
                      headers={"If-Match": d["updated_at"]})  # fmt: skip
    assert again.status_code == 200 and again.json()["geometry"]["text"] == case["text"]
    _inert(again)
    ops = [{"op": "create", "drawing": _text(case["payload"], label)},
           {"op": "update", "id": d["id"], "if_match": again.json()["updated_at"],
            "drawing": _text(case["payload"], label)}]  # fmt: skip
    b = env.c.post("/drawings/batch", json=wire({"operations": ops}, BATCH))
    assert b.status_code == 200, b.text
    _inert(b)
    got = env.listed()
    assert len(got) == 2 and {g["geometry"]["text"] for g in got} == {case["text"]}
    assert all(g.get("label") == (case["label"] if label_ok else None) for g in got)
    assert all(g["geometry"]["text"] == case["text"] for g in got)
    assert "&lt;" not in json.dumps(got) or "&lt;" in case["payload"]  # no encode on the way out


def test_label_corpus_over_the_cap_is_a_422_with_no_echo() -> None:
    env = Env()
    long = [c for c in CORPUS["payloads"] if len(c["payload"]) > 120]
    assert long  # the polyglot: the raw length is checked before stripping (see the models)
    for c in long:
        r = env.c.post("/drawings", json=TRENDLINE | {"label": c["payload"]})
        assert r.status_code == 422, r.text
        assert c["payload"][:20] not in r.text and r.headers["content-type"].startswith(
            "application/problem+json"
        )
    assert env.repo.rows == {}


def test_style_strings_reject_every_corpus_payload() -> None:
    env = Env()  # CSS-injection aimed at style.colour / fill_colour: only #rrggbb is accepted
    for c in CORPUS["payloads"]:
        for key in ("colour", "fill_colour"):
            r = env.c.post("/drawings", json=TRENDLINE | {"style": {key: c["payload"]}})
            assert r.status_code == 422 and c["payload"][:20] not in r.text, (key, c["id"])
    assert env.repo.rows == {}


def test_unicode_amplification_stays_within_the_code_point_caps() -> None:
    env = Env()
    for ch in ("\U0001f680", "e\u0301", "\u0645"):  # 4-byte, combining (2 code points), rtl
        n = len(ch)
        ok = env.c.post("/drawings", json=wire(_text(ch * (1000 // n), ch * (120 // n))))
        assert ok.status_code == 201 and ok.json()["geometry"]["text"] == ch * (1000 // n)
        over = env.c.post("/drawings", json=_text(ch * (1000 // n + 1)))
        assert over.status_code == 422 and over.json()["errors"][0]["rule"] == "string_too_long"
        over = env.c.post("/drawings", json=TRENDLINE | {"label": ch * (120 // n + 1)})
        assert over.status_code == 422 and over.json()["errors"][0]["field"] == "label"
    lone = env.c.post("/drawings", content=json.dumps(_text("\ud800"), ensure_ascii=True))
    assert (
        lone.status_code == 422 and lone.json()["errors"][0]["rule"] == "json_invalid"
    )  # refused at parse


def _ids(n: int) -> list[str]:
    rnd = random.Random(474)  # noqa: S311  # seeded test ids, not security-relevant
    return [str(uuid.UUID(int=i + 1, version=4)) for i in range(n)] + [
        str(uuid.UUID(int=rnd.getrandbits(128), version=4)) for _ in range(n)
    ]


def test_enumerating_ids_never_distinguishes_foreign_missing_or_deleted() -> None:
    env = Env()
    foreign, gone = env.create(), env.create()
    env.c.delete(f"/drawings/{gone['id']}")
    env.user = USER_B
    seen = set()
    for did in [foreign["id"], gone["id"], *_ids(20)]:
        for method, body in (("PUT", wire(TRENDLINE)), ("DELETE", None)):
            r = env.c.request(method, f"/drawings/{did}", json=body)
            assert r.status_code == 404, (method, r.text)
            seen.add(r.text)
            assert foreign["label"] not in r.text and PT["p"] not in r.text
    assert len(seen) == 1  # byte-identical body for foreign, deleted, missing: no per-id oracle
    env.user = USER_A
    assert env.listed() == [foreign] and env.repo.deleted.keys() == {gone["id"]}


def test_foreign_ids_in_a_batch_fail_wholly_and_identically_to_missing_ones() -> None:
    env = Env()
    mine, theirs, gone = env.create(), env.create(), env.create()
    env.c.delete(f"/drawings/{gone['id']}")
    env.user = USER_B
    snapshot = dict(env.repo.rows)
    for victim in (theirs, gone, {"id": str(uuid.uuid4()), "updated_at": mine["updated_at"]}):
        for kind in ("update", "delete"):
            op: dict[str, Any] = {"op": kind, "id": victim["id"], "if_match": victim["updated_at"]}
            ok = {"op": "create", "drawing": TRENDLINE}
            if kind == "update":
                op["drawing"] = TRENDLINE | {"label": "pwned"}
            r = env.c.post("/drawings/batch", json=wire({"operations": [ok, op]}, BATCH))
            assert r.status_code == 409, r.text
            assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
                ("operations.1", "target_unavailable")
            ]
            assert env.repo.rows == snapshot  # the owned create did not survive either


def test_foreign_layout_filter_and_foreign_cursor_leak_nothing() -> None:
    env = Env()
    for _ in range(3):
        env.create()
    page = env.c.get("/drawings", params={"symbol": "BTCUSDT", "limit": "1"}).json()
    cursor = page["meta"]["next_cursor"]
    assert cursor
    env.user = USER_B
    r = env.c.get("/drawings", params={"symbol": "BTCUSDT", "limit": "1",
                                       "cursor": cursor})  # fmt: skip
    # the cursor is an unsigned keyset position, not a capability: it opens nothing of A's
    assert r.status_code == 200 and r.json()["items"] == []
    assert page["items"][0]["id"] not in r.text and cursor not in r.text
    lay = env.c.get("/drawings", params={"symbol": "BTCUSDT", "layout_id": str(uuid.uuid4())})
    assert lay.status_code == 404 and lay.json()["code"] in NOT_FOUND


def test_idempotency_key_replay_across_users_never_returns_the_foreign_response() -> None:
    env = Env()
    key = {"Idempotency-Key": str(uuid.uuid4())}
    body = wire(TRENDLINE | {"label": "owner secret level"})
    first = env.c.post("/drawings", json=body, headers=key)
    assert first.status_code == 201
    env.user = USER_B
    mine = env.c.post("/drawings", json=wire(TRENDLINE | {"label": "mine"}), headers=key)
    assert mine.status_code == 201 and "idempotency-replayed" not in mine.headers
    assert "owner secret level" not in mine.text and mine.json()["owner_user_id"] == str(USER_B)
    same = env.c.post("/drawings", json=body, headers=key)  # B replaying A's exact body+key
    assert same.status_code == 409 and same.json()["code"] == "idempotency_key_reuse"
    assert first.json()["id"] not in same.text
