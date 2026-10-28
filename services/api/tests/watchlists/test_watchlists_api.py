"""`/watchlists` through its router over an in-memory store (E08-T07, #4706): each Gherkin
scenario of the ticket, 22's refusal order, the forbidden role, the outages and the write-ahead
audit. The responses against 22 itself: tests/contract/watchlists/test_watchlists_contract.py;
Postgres (the guarded UPDATE under two writers, the unique index): the integration module."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import httpx
import pytest

from candleviewer.api.watchlists_models import DEFAULT_COLUMNS
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.ingestion.instruments import CatalogueSnapshot
from tests._corpus import rest
from tests.watchlists._watchlists_env import MAJORS, MISSING, SID, USER_A, USER_B, VIEWER, Env, tag

#: The recorded catalogue: BTCUSDT, ETHUSDT and SOLUSDT trade, and LUNAUSDT is closed (delisted).
_PAGE = parse_instruments(rest("rest/instruments_after.json")["result"]["list"], fetched_at_us=0)
CATALOGUE = CatalogueSnapshot({i.symbol: i for i in _PAGE.instruments}, 0)


@pytest.fixture
def env() -> Env:
    return Env(CATALOGUE)


def _put(env: Env, wid: object, body: dict[str, Any], headers: Any = None) -> Any:
    return env.c.put(f"/watchlists/{wid}", json=body, headers=headers)


def test_a_list_round_trips_with_a_version_bumped_by_one_on_each_replace(env: Env) -> None:
    """Scenario: a user's lists round-trip with a version."""
    made = env.c.post("/watchlists", json=MAJORS)
    body = made.json()
    assert (made.status_code, made.headers["ETag"]) == (201, f'W/"{body["id"]}:1"')
    assert (body["symbols"], body["version"]) == (["BTCUSDT", "ETHUSDT"], 1)
    assert body["columns"] == list(DEFAULT_COLUMNS)  # left out: E08-D07's defaults
    assert env.listed() == [body]
    put = _put(env, body["id"], {"name": "Majors", "symbols": ["ETHUSDT", "BTCUSDT"]}, tag(body))
    assert (put.status_code, put.headers["ETag"]) == (200, f'W/"{body["id"]}:2"')
    assert (put.json()["symbols"], put.json()["version"]) == (["ETHUSDT", "BTCUSDT"], 2)
    assert put.json()["created_at"] == body["created_at"] < put.json()["updated_at"]
    assert _put(env, body["id"], MAJORS, tag(put.json())).json()["version"] == 3


def test_a_stale_version_is_412_with_the_current_etag_and_changes_nothing(env: Env) -> None:
    """Scenario: a stale write is refused, never applied silently."""
    made = env.create()
    v2 = _put(env, made["id"], MAJORS | {"name": "Majors 2"}, tag(made)).json()
    stale = _put(env, made["id"], MAJORS | {"name": "Stale"}, tag(made))
    assert (stale.status_code, stale.json()["code"]) == (412, "version_conflict")
    assert stale.headers["ETag"] == f'W/"{made["id"]}:2"'
    assert env.listed() == [v2] and env.conflicts.value == 1
    assert env.audit.actions() == ["watchlist.created", "watchlist.updated"]


@pytest.mark.parametrize(
    "value",
    ["*", 'W/"{id}:1", W/"{id}:2"', 'W/"{other}:1"', '"{id}:1"', 'W/"{id}:0"',
     'W/"{id}:99999999999"', "junk"],
)  # fmt: skip
def test_a_tag_that_names_no_version_of_this_list_never_matches(env: Env, value: str) -> None:
    made = env.create()
    sent = {"If-Match": value.format(id=made["id"], other=MISSING)}
    r = _put(env, made["id"], MAJORS | {"name": "New"}, sent)
    assert (r.status_code, r.headers["ETag"]) == (412, f'W/"{made["id"]}:1"')
    assert env.listed() == [made]


def test_a_replace_without_if_match_is_428_and_changes_nothing(env: Env) -> None:
    made = env.create()
    r = _put(env, made["id"], MAJORS | {"name": "New"})
    assert (r.status_code, r.json()["code"]) == (428, "precondition_required")
    assert env.listed() == [made] and env.conflicts.value == 0


def test_another_users_list_is_a_404_as_a_missing_id_and_nothing_changes(env: Env) -> None:
    """Scenario: lists are private to their owner (IDOR). 22 has no GET by id: the listing never
    shows another user's list, and a GET of an id is 405 whoever holds it."""
    theirs = env.store.seed(USER_B)
    assert env.listed() == []
    as_theirs = {"If-Match": f'W/"{theirs.id}:1"'}
    for wid in (theirs.id, MISSING):
        assert env.c.get(f"/watchlists/{wid}").status_code == 405
    foreign = [_put(env, theirs.id, MAJORS, as_theirs), env.c.delete(f"/watchlists/{theirs.id}")]
    missing = [_put(env, MISSING, MAJORS, as_theirs), env.c.delete(f"/watchlists/{MISSING}")]
    assert [r.status_code for r in foreign + missing] == [404] * 4
    assert [r.content for r in foreign] == [r.content for r in missing]
    assert env.store.rows == {theirs.id: theirs}
    assert [(c["action"], c["object_id"]) for c in env.audit.calls] == [
        ("rbac.denied", str(theirs.id))
    ] * 2  # the two probes of another user's list; an id no one holds leaves no record


def test_a_probe_of_another_users_list_is_audited_rbac_denied_and_the_404_stands(env: Env) -> None:
    """The record `/workspaces` and the presets write for theirs; when it cannot be written, the
    answer is still the 404 of a missing id, so it never tells the two apart."""
    theirs = env.store.seed(USER_B)
    assert env.c.delete(f"/watchlists/{theirs.id}").status_code == 404
    (record,) = env.audit.calls
    assert record == {
        "action": "rbac.denied", "actor_label": str(USER_A), "actor_user_id": USER_A,
        "actor_ip": "10.0.0.9", "session_id": SID, "request_id": None,
        "object_kind": "watchlist", "object_id": str(theirs.id), "outcome": AuditOutcome.DENIED,
        "severity": Severity.WARNING, "reason": "not_owner:workspaces:write:self",
    }  # fmt: skip
    env.audit.fail = AuditUnavailable("wal full")
    unaudited = env.c.delete(f"/watchlists/{theirs.id}")
    assert unaudited.content == env.c.delete(f"/watchlists/{MISSING}").content
    assert unaudited.status_code == 404 and env.store.rows == {theirs.id: theirs}


@pytest.mark.parametrize(
    ("over", "field", "rule", "status"),
    [
        ({"symbols": [f"S{i}USDT" for i in range(201)]}, "symbols", "too_many_symbols", 422),
        ({"symbols": ["BTCUSDT", "XRPUSDT"]}, "symbols", "unknown_symbol", 422),
        ({"symbols": ["BTCUSDT", "LUNAUSDT"]}, "symbols", "unknown_symbol", 422),
        ({"symbols": ["BTCUSDT", "BTCUSDT"]}, "symbols", "duplicate_symbol", 422),
        ({"name": "mAjOrS"}, "name", "name_taken", 409),
    ],
)
def test_an_invalid_list_is_refused_naming_its_field_and_nothing_is_written(
    env: Env, over: dict[str, Any], field: str, rule: str, status: int
) -> None:
    """Scenario: invalid lists are rejected (a delisted symbol is unknown too)."""
    made = env.create()
    r = env.c.post("/watchlists", json=MAJORS | {"name": "Other"} | over)
    assert r.status_code == status
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [(field, rule)]
    assert env.listed() == [made] and env.audit.actions() == ["watchlist.created"]


def test_a_replace_onto_another_lists_name_in_any_case_is_409_name_taken(env: Env) -> None:
    env.create()
    other = env.create(name="Alts", symbols=["SOLUSDT"])
    r = _put(env, other["id"], {"name": "MAJORS", "symbols": []}, tag(other))
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (409, "name_taken")
    assert _put(env, other["id"], {"name": "ALTS", "symbols": []}, tag(other)).status_code == 200


def test_every_write_is_audited_ahead_with_name_count_and_version_never_the_symbols(
    env: Env,
) -> None:
    """Scenario: every write is audited ahead."""
    made = env.create()
    _put(env, made["id"], MAJORS | {"symbols": ["SOLUSDT"]}, tag(made))
    assert env.c.delete(f"/watchlists/{made['id']}").status_code == 204
    created, updated, deleted = env.audit.calls
    v1, v2 = {"name": "Majors", "symbol_count": 2, "version": 1}, {"symbol_count": 1, "version": 2}
    shape = {
        "actor_label": str(USER_A), "actor_user_id": USER_A, "actor_ip": "10.0.0.9",
        "session_id": SID, "request_id": None, "object_kind": "watchlist",
        "object_id": made["id"], "outcome": AuditOutcome.SUCCESS, "severity": Severity.INFO,
    }  # fmt: skip
    assert created == shape | {"action": "watchlist.created", "before_state": None,
                               "after_state": v1}  # fmt: skip
    assert updated == shape | {"action": "watchlist.updated", "before_state": v1,
                               "after_state": v1 | v2}  # fmt: skip
    assert deleted == shape | {"action": "watchlist.deleted", "before_state": v1 | v2,
                               "after_state": None}  # fmt: skip
    for record in (created, updated, deleted):  # pinned by the equalities, said once more
        assert "object_label" not in record and "reason" not in record
    blob = json.dumps(env.audit.calls, default=str)
    assert not [s for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT") if s in blob]


@pytest.mark.parametrize("refusal", [AuditUnavailable("wal full"), RuntimeError("no writer")])
def test_a_refused_record_is_503_audit_unavailable_and_nothing_is_written(
    env: Env, refusal: Exception
) -> None:
    made = env.create()
    env.audit.fail = refusal
    answers = [
        env.c.post("/watchlists", json=MAJORS | {"name": "New"}),
        _put(env, made["id"], MAJORS | {"name": "New"}, tag(made)),
        env.c.delete(f"/watchlists/{made['id']}"),
    ]
    assert {(r.status_code, r.json()["code"]) for r in answers} == {(503, "audit_unavailable")}
    env.audit.fail = None
    assert env.listed() == [made]


def test_a_replace_answers_its_refusals_in_22s_order(env: Env) -> None:
    """413, then 404 (a missing or stale tag never tells another user's list apart), then 428 or
    412, then 422 for the rules that need no catalogue, then 503 instrument_cache_unavailable,
    then 422 unknown_symbol, then 409."""
    made, theirs = env.create(), env.store.seed(USER_B)
    bad = {"name": "", "symbols": ["XRPUSDT"]}
    huge = {"content": b"{" + b" " * (64 * 1024) + b"}", "headers": {"content-type": "x"}}
    assert env.c.put(f"/watchlists/{theirs.id}", **huge).status_code == 413
    assert _put(env, theirs.id, bad).status_code == 404
    assert _put(env, "not-a-uuid", bad).status_code == 404
    assert _put(env, made["id"], bad).status_code == 428
    assert _put(env, made["id"], bad, {"If-Match": "*"}).status_code == 412
    other = env.create(name="Other", symbols=[])
    env.catalogue = None
    taken_twice = {"name": "majors", "symbols": ["XRPUSDT", "XRPUSDT"]}
    taken_new = {"name": "majors", "symbols": ["XRPUSDT"]}
    assert _put(env, other["id"], taken_twice, tag(other)).json()["errors"][0]["rule"] == (
        "duplicate_symbol")  # fmt: skip
    assert _put(env, other["id"], taken_new, tag(other)).json()["code"] == (
        "instrument_cache_unavailable")  # fmt: skip
    env.catalogue = CATALOGUE
    invalid = _put(env, other["id"], taken_new, tag(other))
    assert [(e["field"], e["rule"]) for e in invalid.json()["errors"]] == [
        ("symbols", "unknown_symbol")
    ]
    assert _put(env, other["id"], {"name": "majors", "symbols": []}, tag(other)).status_code == 409
    assert env.listed() == [made, other]


def test_a_viewer_reads_but_every_write_is_403_and_audited_rbac_denied(env: Env) -> None:
    """The forbidden role: `workspaces:write` is refused before any store read."""
    made = env.create()
    env.user = VIEWER
    assert env.listed() == []  # a viewer's own lists: none
    writes = [
        env.c.post("/watchlists", json=MAJORS),
        _put(env, made["id"], MAJORS, tag(made)),
        env.c.delete(f"/watchlists/{made['id']}"),
    ]
    assert [r.status_code for r in writes] == [403] * 3
    assert all(r.json()["required_permissions"] == ["workspaces:write"] for r in writes)
    assert env.audit.actions() == ["watchlist.created"] + ["rbac.denied"] * 3


def test_no_session_is_401_and_no_store_is_503_store_unavailable(env: Env) -> None:
    env.user = None
    assert env.c.get("/watchlists").status_code == env.c.post("/watchlists").status_code == 401
    env.user, env.store_up = USER_A, False
    down = [env.c.get("/watchlists"), env.c.post("/watchlists", json=MAJORS)]
    assert {_retry(r) for r in down} == {(503, "store_unavailable", "5", 5)}
    env.store_up, env.store.fail = True, OSError("connection refused")
    assert env.c.delete(f"/watchlists/{MISSING}").json()["code"] == "store_unavailable"


def _retry(r: Any) -> tuple[int, str, str, int]:
    """A 503 as 22 shapes it: its code, `Retry-After` and `retry_after_seconds`."""
    return (
        r.status_code,
        r.json()["code"],
        r.headers["Retry-After"],
        r.json()["retry_after_seconds"],
    )


def test_with_no_catalogue_only_a_new_symbol_is_503_and_rules_of_shape_come_first(env: Env) -> None:
    """22's `WatchlistSaveUnavailable`, retried after 2 s as the profile writes answer it, and
    only for a symbol the list does not hold yet: a rename, a reorder, a removal and a change of
    columns read no catalogue, nor does a create with no symbols. 201 symbols, or one twice, is
    the 422 that precedes the 503."""
    made = env.create(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    env.catalogue = None
    current = made
    steps = [
        (["BTCUSDT", "ETHUSDT", "SOLUSDT"], None),  # a rename
        (["SOLUSDT", "BTCUSDT", "ETHUSDT"], None),  # a reorder
        (["SOLUSDT", "BTCUSDT"], None),  # a removal
        (["SOLUSDT", "BTCUSDT"], ["last"]),  # a change of columns
    ]
    for symbols, columns in steps:
        body = {"name": "Renamed", "symbols": symbols, "columns": columns}
        r = _put(env, made["id"], body, tag(current))
        assert r.status_code == 200, r.text
        current = r.json()
    back = _put(env, made["id"], {"name": "Renamed", "symbols": ["ETHUSDT"]}, tag(current))
    assert _retry(back) == (503, "instrument_cache_unavailable", "2", 2)
    assert _retry(env.c.post("/watchlists", json=MAJORS | {"name": "New"}))[:2] == (
        503, "instrument_cache_unavailable")  # fmt: skip
    big = {"name": "Big", "symbols": [f"S{i}USDT" for i in range(201)]}
    twice = {"name": "Twice", "symbols": ["XRPUSDT", "XRPUSDT"]}
    refused = [env.c.post("/watchlists", json=b) for b in (big, twice)]
    assert [(r.status_code, r.json()["errors"][0]["rule"]) for r in refused] == [
        (422, "too_many_symbols"), (422, "duplicate_symbol"),
    ]  # fmt: skip
    assert env.c.post("/watchlists", json={"name": "Empty", "symbols": []}).status_code == 201


def test_only_a_symbol_the_list_does_not_hold_yet_is_judged(env: Env) -> None:
    """A symbol delisted after it joined stays through a reorder (21 §3.8.6); the same symbol
    joining a list is `unknown_symbol`."""
    made = env.create(symbols=["SOLUSDT"])
    held = env.store.rows[uuid.UUID(made["id"])]
    env.store.rows[held.id] = replace(held, symbols=("LUNAUSDT", "SOLUSDT"))  # LUNAUSDT closed
    reorder = {"name": "Majors", "symbols": ["SOLUSDT", "LUNAUSDT"]}
    assert _put(env, made["id"], reorder, tag(made)).json()["symbols"] == ["SOLUSDT", "LUNAUSDT"]
    other = env.create(name="Other", symbols=[])
    joins = _put(env, other["id"], {"name": "Other", "symbols": ["LUNAUSDT"]}, tag(other))
    assert (joins.status_code, joins.json()["errors"][0]["rule"]) == (422, "unknown_symbol")


def test_columns_left_out_or_null_store_the_defaults_and_none_may_repeat(env: Env) -> None:
    """On a create and on a replace alike; `[]` stores none; a column twice is 422 on columns."""
    defaults = list(DEFAULT_COLUMNS)
    made = env.create()
    chosen = _put(env, made["id"], MAJORS | {"columns": ["last"]}, tag(made)).json()
    reset = _put(env, made["id"], MAJORS, tag(chosen)).json()
    cleared = _put(env, made["id"], MAJORS | {"columns": []}, tag(reset)).json()
    nulled = _put(env, made["id"], MAJORS | {"columns": None}, tag(cleared)).json()
    stored = [made["columns"], chosen["columns"], reset["columns"], cleared["columns"]]
    assert [*stored, nulled["columns"]] == [defaults, ["last"], defaults, [], defaults]
    twice = env.c.post("/watchlists", json=MAJORS | {"name": "T", "columns": ["last", "last"]})
    assert (twice.status_code, [(e["field"], e["rule"]) for e in twice.json()["errors"]]) == (
        422, [("columns", "duplicate_column")])  # fmt: skip


def test_a_body_past_64_kib_is_413_and_one_not_json_is_422(env: Env) -> None:
    """22: a body over 64 KiB is `413 payload_too_large`, read before anything else."""
    huge = b'{"name": "n", "symbols": [], "columns": ["' + b"x" * 70_000 + b'"]}'
    sent = {"content": huge, "headers": {"content-type": "application/json"}}
    for r in (env.c.post("/watchlists", **sent), env.c.put(f"/watchlists/{MISSING}", **sent)):
        assert (r.status_code, r.json()["code"]) == (413, "payload_too_large")
    bad = env.c.post("/watchlists", content=b"{", headers={"content-type": "application/json"})
    assert (bad.status_code, bad.json()["errors"][0]["rule"]) == (422, "json_invalid")
    assert env.listed() == []


@pytest.mark.parametrize("symbol", ["10000000AIDOGEUSDT", "1000000BABYDOGEUSDT"])
def test_a_long_symbol_is_named_in_its_list_rule_never_redacted(env: Env, symbol: str) -> None:
    """The shared redaction would take an 18-character upper-case run for a key; a list rule's
    entry names only a symbol the `Symbol` pattern admitted, so it is never redacted."""
    for symbols, rule in (([symbol, symbol], "duplicate_symbol"), ([symbol], "unknown_symbol")):
        r = env.c.post("/watchlists", json={"name": "Long", "symbols": symbols})
        (entry,) = r.json()["errors"]
        assert (r.status_code, entry["rule"], entry["message"].split()[0]) == (422, rule, symbol)


def test_a_writer_between_the_read_and_the_replace_is_a_412_naming_its_version(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guarded UPDATE decides: a version that moves after the router's read is the store's
    `WatchlistStaleError`, answered 412 with that version's `ETag` and counted."""
    made, write = env.create(), env.store.replace

    async def raced(owner: uuid.UUID, wid: uuid.UUID, *args: Any, **kw: Any) -> Any:
        env.store.rows[wid] = replace(env.store.rows[wid], version=2)  # another writer commits
        return await write(owner, wid, *args, **kw)

    monkeypatch.setattr(env.store, "replace", raced)
    r = _put(env, made["id"], MAJORS | {"name": "Mine"}, tag(made))
    assert (r.status_code, r.headers["ETag"], env.conflicts.value) == (
        412, f'W/"{made["id"]}:2"', 1)  # fmt: skip
    assert env.audit.actions() == ["watchlist.created"]


def test_a_list_deleted_between_the_read_and_the_replace_is_a_404(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    made, write = env.create(), env.store.replace

    async def vanished(owner: uuid.UUID, wid: uuid.UUID, *args: Any, **kw: Any) -> Any:
        del env.store.rows[wid]  # another session deletes it first
        return await write(owner, wid, *args, **kw)

    monkeypatch.setattr(env.store, "replace", vanished)
    r = _put(env, made["id"], MAJORS | {"name": "Mine"}, tag(made))
    assert (r.status_code, r.json()["code"], env.store.rows) == (404, "not_found", {})


async def test_a_streamed_body_past_64_kib_with_no_length_is_413(env: Env) -> None:
    """With no `Content-Length` the stream is read only until it passes the cap."""
    pulled: list[int] = []

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(64):  # 64 chunks of 4 KiB: 256 KiB on offer
            pulled.append(1)
            yield b" " * 4096

    transport = httpx.ASGITransport(app=env.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/watchlists", content=chunks(),
                              headers={"content-type": "application/json"})  # fmt: skip
    assert (r.status_code, r.json()["code"]) == (413, "payload_too_large")
    assert "content-length" not in r.request.headers and len(pulled) <= 64 * 1024 // 4096 + 1
    assert env.listed() == []
