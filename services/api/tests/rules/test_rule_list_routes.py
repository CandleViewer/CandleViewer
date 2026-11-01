"""#2291 (SR-051): the `GET /rules` cursor and the version reads over HTTP.

`listRules` pages by rule id: a `cursor` that is not one is `400 invalid_cursor` (22), answered
before the manager is called, and one that is positions the caller's own page whatever rule it
names. The two version reads answer from one read in the caller's scope, and every read needs
`rules:read` before the store is read at all.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.rules.manager import Actor, GrantRead, RuleRow, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rule_list_scope import MGR, OTHER, PERMS, A, Recording, _rid, _rule, _vid

_PROBLEM = "application/problem+json"


class _Api:
    """The `/rules` read routes over a recording store, for one caller."""

    def __init__(self, *rows: RuleRow, perms: frozenset[str] = PERMS, user: str = MGR) -> None:
        self.store = Recording()
        self.store.seed(*rows)
        mgr = RulesManager(self.store, default_registry())
        actor = Actor(user, "s", perms, frozenset({A}))

        def resolve(_request: Request) -> Actor:
            return actor

        app = FastAPI()
        app.include_router(make_rules_crud_router(lambda: mgr, resolve))
        self.c = TestClient(app)

    def ids(self, **query: Any) -> list[str]:
        resp = self.c.get("/rules", params=query)
        assert resp.status_code == 200, resp.text
        return [str(i["id"]) for i in resp.json()["items"]]


@pytest.mark.parametrize(
    "cursor",
    ["zzz-not-a-rule", "00000000-0000-4000-8000-00000000001", "' OR 1=1 --", "q" * 300],
    ids=["word", "short-uuid", "sql", "long"],
)
def test_a_cursor_that_is_not_a_rule_id_is_400_invalid_cursor(cursor: str) -> None:
    api = _Api(_rule(_rid(1), MGR, (A,)))
    resp = api.c.get("/rules", params={"cursor": cursor})
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith(_PROBLEM)
    body = resp.json()
    assert (body["code"], body["title"], body["detail"]) == (
        "invalid_cursor",
        "Pagination cursor is malformed or expired",
        "The cursor is not a rule id.",
    )
    assert cursor not in resp.text  # the detail names the cursor, never its value
    assert api.store.reads == []  # refused before the manager is called


def test_an_empty_cursor_is_the_first_page() -> None:
    api = _Api(_rule(_rid(1), MGR, (A,)), _rule(_rid(2), MGR, (A,)))
    assert api.ids(cursor="") == api.ids() == [_rid(1), _rid(2)]


def test_a_cursor_in_upper_case_reads_as_its_canonical_id() -> None:
    api = _Api(*(_rule(_rid(n), MGR, (A,)) for n in (1, 2, 3)))
    assert api.ids(cursor=_rid(1).upper()) == api.ids(cursor=_rid(1)) == [_rid(2), _rid(3)]
    assert api.ids(cursor="{" + _rid(2).upper() + "}") == [_rid(3)]
    afters = [asked["after"] for method, _, asked in api.store.reads if method == "scoped_page"]
    assert afters == [_rid(1), _rid(1), _rid(2)]


def test_a_cursor_naming_another_users_rule_serves_only_the_callers_rows() -> None:
    """A cursor positions the keyset and never widens it: after another user's rule id, or an id
    no rule holds, the page is the caller's own rows after it (IDOR)."""
    api = _Api(
        _rule(_rid(1), MGR, (A,)),
        _rule(_rid(2), OTHER, (A,)),
        _rule(_rid(3), MGR, (A,)),
        _rule(_rid(4), OTHER, (A,)),
        _rule(_rid(6), MGR, ()),
    )
    assert api.ids(cursor=_rid(2)) == [_rid(3), _rid(6)]
    assert api.ids(cursor=_rid(5)) == [_rid(6)]
    assert api.ids(cursor=_rid(9)) == []


def test_the_version_routes_answer_from_one_scoped_read() -> None:
    rid = _rid(1)
    api = _Api(_rule(rid, MGR, (A,), (A,)))
    listed = api.c.get(f"/rules/{rid}/versions")
    assert listed.status_code == 200, listed.text
    assert [v["version"] for v in listed.json()["items"]] == [2, 1]
    assert listed.json()["meta"] == {"next_cursor": None, "has_more": False, "count": 2}
    one = api.c.get(f"/rules/{rid}/versions/{_vid(rid, 1)}")
    assert one.status_code == 200, one.text
    assert (one.json()["id"], one.json()["version"]) == (_vid(rid, 1), 1) and "ir" in one.json()
    missing = api.c.get(f"/rules/{rid}/versions/{_vid(rid, 9)}")
    assert (missing.status_code, missing.json()["detail"]) == (404, "That version does not exist.")
    point = {"mode": None, "level": None, "after": None, "limit": 1, "only": rid}
    assert api.store.reads == [("scoped_page", GrantRead(MGR, frozenset({A})), point)] * 3


@pytest.mark.parametrize(
    "path",
    [
        "/rules",
        f"/rules/{_rid(1)}",
        f"/rules/{_rid(1)}/versions",
        f"/rules/{_rid(1)}/versions/{_rid(2)}",
    ],
)
def test_a_caller_without_rules_read_is_403_before_any_store_read(path: str) -> None:
    api = _Api(_rule(_rid(1), MGR, (A,)), perms=frozenset({"rules:write"}))
    resp = api.c.get(path)
    assert (resp.status_code, resp.json()["code"]) == (403, "forbidden")
    assert api.store.reads == []
