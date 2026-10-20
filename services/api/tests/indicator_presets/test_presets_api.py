"""`/indicator-presets` through the router (E13-T03, #427): the four operations, their response
shape, A4 (names unique per user and indicator), A5 (soft delete), `immutable_field`, the 500
cap and 22's evaluation order. RBAC and IDOR are `test_presets_api_rbac.py`; validation is
`test_presets_validation.py`; the audit records are `test_presets_audit.py`."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from _presets_env import BUILTIN_IDS, EMA9, PRESET_KEYS, USER_A, VIEWER, Env, body

from candleviewer.api.indicator_presets import make_indicator_presets_router
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.orderflow.indicators.catalogue import default_catalogue
from candleviewer.orderflow.indicators.limits import PRESETS_PER_USER_MAX
from candleviewer.storage.repositories.indicator_presets import PresetShapeError
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

MISSING = "00000000-0000-4000-8000-0000000000ff"


def test_create_answers_201_with_exactly_the_contract_fields_owned_by_the_caller() -> None:
    env = Env()
    made = env.create()
    assert set(made) == PRESET_KEYS
    assert (made["owner_user_id"], made["is_builtin"]) == (str(USER_A), False)
    assert made["params"] == {"n": 14} and made["style"] == {}
    assert made["created_at"] == made["updated_at"]
    assert made["created_at"].endswith("Z") and len(made["created_at"]) == 27


def test_list_is_builtins_first_then_the_callers_presets_by_code_and_name() -> None:
    env = Env()
    env.create(name="b", indicator_code="sma", params={"n": 20}, pane_target="overlay")
    env.create(name="B2", indicator_code="atr")
    env.create(name="a", indicator_code="atr")
    items = env.listed()
    assert [i["id"] for i in items[: len(BUILTIN_IDS)]] == [
        r.id for r in sorted(env.repo.rows.values(), key=lambda r: (r.indicator_code,
                                                                     r.name.lower(), r.id))
        if r.is_builtin
    ]  # fmt: skip
    assert [(i["indicator_code"], i["name"]) for i in items[len(BUILTIN_IDS) :]] == [
        ("atr", "a"), ("atr", "B2"), ("sma", "b"),
    ]  # fmt: skip
    assert all(set(i) == PRESET_KEYS for i in items)
    builtin = next(i for i in items if i["id"] == EMA9)
    assert (builtin["owner_user_id"], builtin["is_builtin"]) == (None, True)


def test_update_is_a_full_replacement_whose_omitted_fields_take_their_defaults() -> None:
    env = Env()
    made = env.create(is_favourite=True, pane_target="subpane")
    replacement = {"name": "ATR 20", "indicator_code": "atr", "params": {"n": 20}}
    r = env.c.put(f"/indicator-presets/{made['id']}", json=replacement)
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["name"], got["params"], got["pane_target"], got["is_favourite"]) == (
        "ATR 20", {"n": 20}, "overlay", False,
    )  # fmt: skip
    assert got["created_at"] == made["created_at"] and got["updated_at"] > made["updated_at"]


def test_indicator_code_is_immutable_on_put() -> None:
    env = Env()
    made = env.create()
    r = env.c.put(f"/indicator-presets/{made['id']}",
                  json=body(indicator_code="ema", params={"n": 14}))  # fmt: skip
    assert r.status_code == 422
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
        ("indicator_code", "immutable_field")
    ]
    assert env.mine()[0]["indicator_code"] == "atr"


def test_fast_then_fast_is_409_name_taken_existing_untouched() -> None:
    """A4: names are unique per user and indicator, case-insensitive (`ux_ip_name`)."""
    env = Env()
    fast = env.create(name="Fast", indicator_code="ema", params={"n": 9})
    r = env.c.post("/indicator-presets", json=body(name="fast", indicator_code="ema",
                                                    params={"n": 12}))  # fmt: skip
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"
    assert r.json()["errors"] == [{"field": "name", "rule": "name_taken",
                                   "message": "You already have a preset with this name for "
                                              "this indicator."}]  # fmt: skip
    assert env.mine() == [fast]


def test_the_same_name_is_free_for_another_indicator_another_user_and_a_builtin_copy() -> None:
    env = Env()
    env.create(name="Fast", indicator_code="ema", params={"n": 9})
    env.create(name="Fast", indicator_code="sma", params={"n": 9})
    env.create(name="ema(9)", indicator_code="ema", params={"n": 9})  # a built-in's name
    env.user = uuid.UUID("00000000-0000-4000-8000-00000000000b")
    env.create(name="Fast", indicator_code="ema", params={"n": 9})


def test_renaming_onto_a_held_name_is_409_and_onto_its_own_name_is_fine() -> None:
    env = Env()
    env.create(name="Fast")
    slow = env.create(name="Slow")
    r = env.c.put(f"/indicator-presets/{slow['id']}", json=body(name="FAST"))
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (409, "name_taken")
    assert env.c.put(f"/indicator-presets/{slow['id']}", json=body(name="SLOW")).status_code == 200


def test_the_501st_live_preset_is_409_limit_reached_and_a_delete_frees_a_slot() -> None:
    env = Env()
    for i in range(PRESETS_PER_USER_MAX):
        env.create(name=f"p{i}")
    r = env.c.post("/indicator-presets", json=body(name="one too many"))
    assert r.status_code == 409
    assert r.json()["errors"] == [{"rule": "limit_reached", "message": "You have reached the "
                                   "limit of saved indicator presets."}]  # fmt: skip
    first = env.mine()[0]["id"]
    assert env.c.delete(f"/indicator-presets/{first}").status_code == 204
    env.create(name="one too many")


def test_delete_hides_the_preset_keeps_the_row_and_a_second_delete_is_404() -> None:
    """A5: `deleted_at` is set, the row remains, and it no longer appears in list responses."""
    env = Env()
    made = env.create()
    r = env.c.delete(f"/indicator-presets/{made['id']}")
    assert (r.status_code, r.text) == (204, "")
    assert made["id"] in env.repo.rows and made["id"] in env.repo.deleted
    assert env.mine() == []
    assert env.c.delete(f"/indicator-presets/{made['id']}").status_code == 404
    assert env.c.put(f"/indicator-presets/{made['id']}", json=body()).status_code == 404
    env.create()  # its name is free again


def test_get_by_id_is_405_and_discloses_nothing() -> None:
    """Ruling Q3: no read by id; the answer is the same for a built-in, a foreign and a missing
    id, so it is no existence oracle."""
    env = Env()
    mine = env.create()
    answers = {env.c.get(f"/indicator-presets/{pid}").status_code
               for pid in (mine["id"], EMA9, MISSING, "not-a-uuid")}  # fmt: skip
    assert answers == {405}


def test_a_bad_preset_id_is_422_uuid_parsing_before_any_store_read() -> None:
    env = Env()
    for method in ("PUT", "DELETE"):
        r = env.c.request(method, "/indicator-presets/not-a-uuid", json=body())
        assert r.status_code == 422
        assert r.json()["errors"] == [{"field": "presetId", "rule": "uuid_parsing",
                                       "message": "presetId must be a UUID."}]  # fmt: skip
    assert [name for name, _ in env.repo.calls] == []


def test_the_id_is_case_insensitive_and_answered_canonical() -> None:
    env = Env()
    made = env.create()
    r = env.c.put(f"/indicator-presets/{made['id'].upper()}", json=body(name="Upper"))
    assert (r.status_code, r.json()["id"]) == (200, made["id"])


def test_evaluation_order_413_then_422_path_then_query_then_body_then_404() -> None:
    """22 `updateIndicatorPreset`: 413; 422 (path, query, body, none of which reads a stored
    preset); 404; 403 `builtin_immutable`; 422 `immutable_field`; 409; the write."""
    env = Env()
    huge = b"{" + b" " * (16 * 1024) + b"}"
    assert env.c.put("/indicator-presets/not-a-uuid?x=1", content=huge).status_code == 413
    r = env.c.put("/indicator-presets/not-a-uuid?x=1", json={"name": 1})
    assert r.json()["errors"][0]["rule"] == "uuid_parsing"
    r = env.c.put(f"/indicator-presets/{MISSING}?x=1", json={"name": 1})
    assert r.json()["errors"][0]["rule"] == "undeclared_parameter"
    r = env.c.put(f"/indicator-presets/{MISSING}", json=body(params={"n": 0}))
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (422, "minimum")
    assert env.repo.calls == []  # nothing so far read a stored preset
    r = env.c.put(f"/indicator-presets/{EMA9}", json=body(indicator_code="ema", params={"n": 9}))
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (403, "builtin_immutable")
    assert env.c.put(f"/indicator-presets/{MISSING}", json=body()).status_code == 404


def test_no_store_is_503_store_unavailable_after_validation() -> None:
    env = Env()
    env.repo_up = False
    assert env.c.post("/indicator-presets", json=body(params={"n": 0})).status_code == 422
    for r in (env.c.get("/indicator-presets"), env.c.post("/indicator-presets", json=body()),
              env.c.put(f"/indicator-presets/{MISSING}", json=body()),
              env.c.delete(f"/indicator-presets/{MISSING}")):  # fmt: skip
        assert (r.status_code, r.json()["code"]) == (503, "store_unavailable")
        assert r.headers["retry-after"] == "5"


def test_a_shape_check_the_store_refuses_is_a_422_never_a_500() -> None:
    """The DB CHECKs `ip_params_shape` / `ip_style_shape` back the API's own size check."""
    env = Env()

    async def refused(owner: str, preset_id: str, fields: Any) -> Any:
        raise PresetShapeError("params")

    env.repo.create = refused  # type: ignore[method-assign]  # the store's backstop fires
    r = env.c.post("/indicator-presets", json=body())
    assert r.status_code == 422
    message = "params is larger than a preset may store."
    assert r.json()["errors"] == [{"field": "params", "rule": "params_too_large",
                                   "message": message}]  # fmt: skip


def test_a_delete_that_loses_a_race_with_another_delete_is_404() -> None:
    env = Env()
    made = env.create()

    async def gone(owner: str, preset_id: str) -> bool:
        return False  # deleted by a concurrent request after the lookup

    env.repo.soft_delete = gone  # type: ignore[method-assign]  # simulates the lost race
    assert env.c.delete(f"/indicator-presets/{made['id']}").status_code == 404


def test_the_router_refuses_to_be_built_without_an_audit_emitter() -> None:
    with pytest.raises(TypeError, match="audit emitter is required"):
        make_indicator_presets_router(lambda: None, None, None, default_catalogue())  # type: ignore[arg-type]  # the refusal is the point


def test_every_problem_carries_the_registry_title_of_its_code() -> None:
    """`title` is the `x-error-codes` registry's (`ERROR_META`, generated from 22), the same
    string every other router answers for that code, for all eight codes this one emits."""
    env = Env()
    made = env.create()
    answered = [
        env.c.post("/indicator-presets", json=body()),  # 409 name_taken
        env.c.post("/indicator-presets", json=body(params={"n": 0})),  # 422
        env.c.delete(f"/indicator-presets/{MISSING}"),  # 404
        env.c.post("/indicator-presets", content=b"{" + b" " * (16 * 1024) + b"}"),  # 413
    ]
    env.audit.fail = AuditUnavailable("down")
    answered.append(env.c.delete(f"/indicator-presets/{made['id']}"))  # 503 audit_unavailable
    env.audit.fail = None
    env.repo_up = False
    answered.append(env.c.get("/indicator-presets"))  # 503 store_unavailable
    env.user = VIEWER
    answered.append(env.c.post("/indicator-presets", json=body()))  # 403
    env.user = None
    answered.append(env.c.get("/indicator-presets"))  # 401
    problems = [r.json() for r in answered]
    assert sorted(p["code"] for p in problems) == [
        "audit_unavailable", "conflict", "forbidden", "not_found", "payload_too_large",
        "store_unavailable", "unauthenticated", "validation_failed",
    ]  # fmt: skip
    for problem in problems:
        assert problem["title"] == ERROR_META[ErrorCode(problem["code"])].title, problem["code"]
