"""`/scanner/presets*` and `/scanner/criteria` through the router (E08-T09 PR 2a, #4708): the
operations, their response shape, the name rule, the default, `version`, the hard delete, the
100 cap, `unavailable_criteria` and 22's evaluation order. RBAC and IDOR are
`test_scanner_presets_rbac.py`; the audit records are `test_scanner_presets_audit.py`."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from _scanner_env import MISSING, MOMENTUM, PRESET_KEYS, USER_A, USER_B, Env, body
from pydantic import ValidationError

from candleviewer.api.scanner_criteria import CRITERIA, REGIME_CLASSES, SORT_KEYS
from candleviewer.api.scanner_presets_models import ScannerPresetInput
from candleviewer.storage.repositories.scanner_presets import MAX_PRESETS


def test_create_answers_201_with_exactly_the_contract_fields_and_version_1() -> None:
    env = Env()
    made = env.create()
    assert set(made) == PRESET_KEYS
    assert (made["name"], made["filter"], made["sort"]) == ("Momentum", MOMENTUM["filter"],
                                                            "turnover_24h")  # fmt: skip
    assert (made["version"], made["is_default"], made["unavailable_criteria"]) == (1, False, [])
    assert made["created_at"] == made["updated_at"] and made["created_at"].endswith("Z")
    assert "results" not in made and "user_id" not in made


def test_omitted_sort_and_is_default_take_their_defaults() -> None:
    env = Env()
    r = env.c.post("/scanner/presets", json={"name": "Bare", "filter": {}})
    assert r.status_code == 201, r.text
    assert (r.json()["sort"], r.json()["is_default"], r.json()["filter"]) == (
        "turnover_24h", False, {},
    )  # fmt: skip


def test_list_is_the_callers_presets_by_case_insensitive_name_then_id() -> None:
    env = Env()
    for name in ("beta", "Alpha", "gamma"):
        env.create(name=name)
    env.repo.seed(USER_B, "aardvark")  # another user's: never listed
    assert [i["name"] for i in env.listed()] == ["Alpha", "beta", "gamma"]
    assert all(set(i) == PRESET_KEYS for i in env.listed())


def test_update_is_a_full_replacement_that_raises_version() -> None:
    env = Env()
    made = env.create(sort="funding_rate", is_default=True)
    r = env.c.put(f"/scanner/presets/{made['id']}", json={"name": "Renamed", "filter": {}})
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["name"], got["filter"], got["sort"], got["is_default"]) == (
        "Renamed", {}, "turnover_24h", False,
    )  # fmt: skip
    assert got["version"] == 2 and got["created_at"] == made["created_at"]
    assert got["updated_at"] > made["updated_at"]


def test_names_are_unique_per_user_case_insensitive_and_free_for_another_user() -> None:
    env = Env()
    first = env.create(name="Momentum")
    r = env.c.post("/scanner/presets", json=body(name="MOMENTUM"))
    assert (r.status_code, r.json()["code"]) == (409, "conflict")
    assert r.json()["errors"] == [{"field": "name", "rule": "name_taken",
                                   "message": "You already have a scanner preset with this "
                                              "name."}]  # fmt: skip
    other = env.create(name="Other")
    taken = env.c.put(f"/scanner/presets/{other['id']}", json=body(name="momentum"))
    assert (taken.status_code, taken.json()["errors"][0]["rule"]) == (409, "name_taken")
    same = env.c.put(f"/scanner/presets/{first['id']}", json=body(name="MoMeNtUm"))
    assert same.status_code == 200
    env.user = USER_B
    env.create(name="Momentum")


def test_the_101st_preset_is_409_limit_reached_and_a_delete_frees_a_slot() -> None:
    env = Env()
    for i in range(MAX_PRESETS):
        env.repo.seed(USER_A, f"p{i}")
    r = env.c.post("/scanner/presets", json=body(name="one too many"))
    assert r.status_code == 409
    assert r.json()["errors"] == [{"rule": "limit_reached", "message": "You have reached the "
                                   "limit of saved scanner presets."}]  # fmt: skip
    first = env.listed()[0]["id"]
    assert env.c.delete(f"/scanner/presets/{first}").status_code == 204
    env.create(name="one too many")


def test_one_default_per_user_setting_one_clears_the_previous_and_raises_its_version() -> None:
    env = Env()
    first = env.create(name="First", is_default=True)
    second = env.create(name="Second", is_default=True)
    by_id = {i["id"]: i for i in env.listed()}
    assert by_id[second["id"]]["is_default"] and not by_id[first["id"]]["is_default"]
    assert by_id[first["id"]]["version"] == 2
    again = env.c.put(f"/scanner/presets/{first['id']}", json=body(name="First", is_default=True))
    assert again.status_code == 200
    by_id = {i["id"]: i for i in env.listed()}
    assert [i["name"] for i in by_id.values() if i["is_default"]] == ["First"]
    assert by_id[second["id"]]["version"] == 2


def test_delete_is_hard_its_name_is_free_again_and_a_second_delete_is_404() -> None:
    env = Env()
    made = env.create(is_default=True)
    r = env.c.delete(f"/scanner/presets/{made['id']}")
    assert (r.status_code, r.text) == (204, "")
    assert made["id"] not in env.repo.rows and env.listed() == []
    assert env.c.delete(f"/scanner/presets/{made['id']}").status_code == 404
    assert env.c.put(f"/scanner/presets/{made['id']}", json=body()).status_code == 404
    env.create()


def test_a_stored_criterion_the_server_no_longer_knows_is_flagged_never_dropped() -> None:
    env = Env()
    stored = {"turnover_24h": {"min": "1"}, "volatility": {"min": "2"}, "old_one": {"max": "3"}}
    pid = env.repo.seed(USER_A, "Old", filter=stored)
    (item,) = env.listed()
    assert item["filter"] == {"turnover_24h": {"min": "1"}}
    assert item["unavailable_criteria"] == ["old_one", "volatility"]
    assert env.repo.rows[pid].filter == stored  # still stored as written
    saved = env.c.put(f"/scanner/presets/{pid}", json={"name": "Old", "filter": item["filter"]})
    assert (saved.json()["unavailable_criteria"], env.repo.rows[pid].filter) == (
        [], {"turnover_24h": {"min": "1"}},
    )  # fmt: skip


def test_get_by_id_is_405_for_every_id() -> None:
    env = Env()
    mine = env.create()
    answers = {env.c.get(f"/scanner/presets/{pid}").status_code
               for pid in (mine["id"], MISSING, "not-a-uuid")}  # fmt: skip
    assert answers == {405}


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_a_bad_preset_id_is_422_uuid_parsing_before_any_store_read(method: str) -> None:
    env = Env()
    r = env.c.request(method, "/scanner/presets/not-a-uuid", json=body())
    assert r.status_code == 422
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [("presetId", "uuid_parsing")]
    assert env.repo.calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/scanner/presets"), ("POST", "/scanner/presets"), ("GET", "/scanner/criteria"),
     ("PUT", f"/scanner/presets/{MISSING}"), ("DELETE", f"/scanner/presets/{MISSING}")],
)  # fmt: skip
def test_any_query_parameter_is_refused_422_before_anything_is_read(method: str, path: str) -> None:
    env = Env()
    r = env.c.request(method, path, params={"user_id": str(USER_B)}, json=body())
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert env.repo.calls == [] and env.audit.calls == []


def test_a_body_over_8_kib_is_413_before_it_is_parsed() -> None:
    env = Env()
    huge = b'{"name": "x", "filter": {}, "pad": "' + b"x" * 8192 + b'"}'
    for r in (
        env.c.post("/scanner/presets", content=huge, headers={"content-type": "application/json"}),
        env.c.put(f"/scanner/presets/{MISSING}", content=huge,
                  headers={"content-type": "application/json"}),
    ):  # fmt: skip
        assert (r.status_code, r.json()["code"]) == (413, "payload_too_large")
    assert env.repo.calls == []


def _rules(r: Any) -> list[tuple[str, str]]:
    assert r.status_code == 422, r.text
    return [(e["field"], e["rule"]) for e in r.json()["errors"]]


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({"id": str(uuid.uuid4())}, [("id", "extra_forbidden")]),
        ({"version": 3}, [("version", "extra_forbidden")]),
        ({"unavailable_criteria": []}, [("unavailable_criteria", "extra_forbidden")]),
        ({"results": []}, [("results", "extra_forbidden")]),
        ({"name": "x" * 81}, [("name", "string_too_long")]),
        ({"name": " \x00 "}, [("name", "string_too_short")]),
        ({"sort": "regime"}, [("sort", "literal_error")]),
        ({"is_default": "yes"}, [("is_default", "bool_type")]),
        ({"filter": []}, [("filter", "dict_type")]),
        ({"filter": {"volatility": {"min": "1"}}}, [("filter", "unknown_criterion")]),
        ({"filter": {"funding_rate": {}}}, [("filter.funding_rate", "range_empty")]),
        ({"filter": {"funding_rate": {"min": 1}}}, [("filter.funding_rate", "invalid_decimal")]),
        ({"filter": {"funding_rate": {"min": "1e-3"}}},
         [("filter.funding_rate", "invalid_decimal")]),
        ({"filter": {"funding_rate": {"min": "1", "step": "2"}}},
         [("filter.funding_rate", "extra_forbidden")]),
        ({"filter": {"funding_rate": "1"}}, [("filter.funding_rate", "dict_type")]),
        ({"filter": {"funding_rate": {"min": "0.001", "max": "0.001"}}},
         [("filter.funding_rate", "range_inverted")]),
        ({"filter": {"funding_rate": {"min": "0.01", "max": "-0.01"}}},
         [("filter.funding_rate", "range_inverted")]),
        ({"filter": {"regime": {"classes": []}}}, [("filter.regime", "classes_empty")]),
        ({"filter": {"regime": {"classes": ["sideways"]}}},
         [("filter.regime", "unknown_regime_class")]),
        ({"filter": {"regime": {"classes": ["range", "range"]}}},
         [("filter.regime", "non_unique_items")]),
        ({"filter": {"regime": {}}}, [("filter.regime", "missing")]),
        ({"filter": {"regime": {"classes": "range"}}}, [("filter.regime", "list_type")]),
        ({"filter": {"regime": {"classes": ["range"], "x": 1}}},
         [("filter.regime", "extra_forbidden")]),
    ],
)  # fmt: skip
def test_each_contract_rule_is_a_422_naming_its_field(
    over: dict[str, Any], expected: list[tuple[str, str]]
) -> None:
    env = Env()
    assert _rules(env.c.post("/scanner/presets", json=body(**over))) == expected
    assert not any(name == "create" for name, _ in env.repo.calls)  # nothing stored


def test_a_lone_surrogate_name_is_refused_on_the_wire_and_by_the_model() -> None:
    """The JSON parser refuses an escaped lone surrogate first (`json_invalid`); the DTO's own
    `invalid_unicode` covers a value decoded elsewhere (22 `ScannerPresetInput`)."""
    env = Env()
    sent = json.dumps(body(name="a\ud800"))  # ASCII-escaped: `\ud800` reaches the parser
    r = env.c.post("/scanner/presets", content=sent, headers={"content-type": "application/json"})
    assert r.status_code == 422 and env.repo.calls == []
    with pytest.raises(ValidationError) as err:
        ScannerPresetInput.model_validate(body(name="a\ud800"))
    assert err.value.errors()[0]["type"] == "invalid_unicode"


def test_a_filter_over_4_kib_as_stored_is_422_filter_too_large() -> None:
    env = Env()
    classes = {"classes": ["trend_up"]}
    big = {"turnover_24h": {"min": "1" * 4100}, "regime": classes}
    assert _rules(env.c.post("/scanner/presets", json=body(filter=big))) == [
        ("filter", "filter_too_large")
    ]


def test_several_defects_are_reported_together_and_never_echo_a_value() -> None:
    env = Env()
    bad = {"funding_rate": {"min": "5", "max": "1"}, "spread_bps": {}, "s3cr3t_key": {}}
    r = env.c.post("/scanner/presets", json=body(filter=bad))
    assert sorted(_rules(r)) == [("filter", "unknown_criterion"),
                                 ("filter.funding_rate", "range_inverted"),
                                 ("filter.spread_bps", "range_empty")]  # fmt: skip
    assert "s3cr3t_key" not in r.text and '"5"' not in r.text


def test_json_nested_too_deep_is_422_before_the_dto() -> None:
    env = Env()
    deep = '{"name": "x", "filter": ' + "[" * 40 + "]" * 40 + "}"
    r = env.c.post("/scanner/presets", content=deep, headers={"content-type": "application/json"})
    assert _rules(r) == [("", "json_too_deep")]


def test_a_body_that_is_not_utf8_json_is_422() -> None:
    env = Env()
    r = env.c.post("/scanner/presets", content=b"\xff\xfe",
                   headers={"content-type": "application/json"})  # fmt: skip
    assert _rules(r) == [("", "json_invalid")]


def test_criteria_lists_the_eight_in_order_with_regime_classes() -> None:
    env = Env()
    r = env.c.get("/scanner/criteria")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["id"] for i in items] == [c.id for c in CRITERIA]
    regime = items[-1]
    assert (regime["kind"], regime["unit"], regime["classes"]) == (
        "class_set", "class", list(REGIME_CLASSES),
    )  # fmt: skip
    assert all("classes" not in i for i in items[:-1])
    assert env.repo.calls == []  # a static catalogue: no store read


def test_criteria_carry_their_availability_and_the_sort_keys_theirs() -> None:
    got = Env().c.get("/scanner/criteria").json()
    assert set(got) == {"items", "sort_keys"}
    assert {i["id"] for i in got["items"] if not i["available"]} == {
        "oi_change_pct_24h", "tape_speed_zscore", "regime",
    }  # fmt: skip
    assert [k["id"] for k in got["sort_keys"]] == list(SORT_KEYS)
    assert {k["id"] for k in got["sort_keys"] if not k["available"]} == {
        "cvd", "tape_speed", "liquidation_intensity", "tape_speed_zscore", "oi_change_pct_24h",
    }  # fmt: skip


@pytest.mark.parametrize("method", ["post", "put"])
def test_a_write_naming_an_unavailable_criterion_or_sort_is_422_and_stores_nothing(
    method: str,
) -> None:
    env = Env()
    pid = env.create()["id"] if method == "put" else None
    env.repo.calls.clear()
    flt = MOMENTUM["filter"] | {"regime": {"classes": ["calm"]}, "tape_speed_zscore": {"min": "2"}}
    sent = body(filter=flt, sort="cvd")
    r = (env.c.post("/scanner/presets", json=sent) if pid is None
         else env.c.put(f"/scanner/presets/{pid}", json=sent))  # fmt: skip
    assert sorted(_rules(r)) == [("filter.regime", "criterion_unavailable"),
                                 ("filter.tape_speed_zscore", "criterion_unavailable"),
                                 ("sort", "criterion_unavailable")]  # fmt: skip
    assert env.repo.calls == []  # refused before any store read (22's order)


def test_a_stored_unavailable_criterion_and_sort_are_flagged_never_dropped() -> None:
    env = Env()
    stored = {"turnover_24h": {"min": "1"}, "regime": {"classes": ["calm"]}}
    pid = env.repo.seed(USER_A, "Flow", filter=stored, sort="liquidation_intensity")
    (item,) = env.listed()
    assert (item["filter"], item["sort"]) == ({"turnover_24h": {"min": "1"}},
                                              "liquidation_intensity")  # fmt: skip
    assert item["unavailable_criteria"] == ["liquidation_intensity", "regime"]
    assert (env.repo.rows[pid].filter, env.repo.rows[pid].sort) == (
        stored, "liquidation_intensity",
    )  # fmt: skip
