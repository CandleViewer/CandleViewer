"""#2445: the Owner's `AuditEntry` carries every contract field (#2392); a Manager's
projection (SR-067) keeps only the allow-list. Only the Owner's raw view reads the
Owner-only columns, and its `detail` comes from the page's capped chain renderings: a state
withheld by the size caps is null and listed in `elided`, a stored null never is (#2446)."""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any

import httpx
import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from fastapi import FastAPI, Request

from candleviewer.api.audit import make_audit_router
from candleviewer.audit import query as query_mod
from candleviewer.audit.access import (
    OWN_REDACTED_FIELDS,
    AuditPrincipal,
    AuditView,
    redact_entry_for_view,
)
from candleviewer.audit.models import AuditEntry, AuditOutcome, AuditPage, ExchangeEnv, Severity
from candleviewer.audit.query import STATE_MAX_DEPTH, AuditQueryService

#: Every property of the contract's `AuditEntry` schema (#2392), hand-copied until the
#: generated model is on this stack.
CONTRACT_FIELDS = frozenset(
    {
        "id", "ts", "actor_user_id", "actor_username", "action", "subject_type",
        "subject_id", "subject_label", "outcome", "severity", "reason", "environment",
        "session_id", "ip", "user_agent", "request_id", "detail", "entry_hash", "prev_hash",
    }
)  # fmt: skip
#: The states of the contract's `detail` (#2446); `elided` lists the withheld ones.
DETAIL_STATES = ("before", "after")

_SESSION = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
_ACTOR = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
_REQUEST = uuid.UUID("00000000-0000-4000-8000-0000000000cc")


def _assert_detail_shape(detail: dict[str, Any]) -> None:
    """Contract #2446: `before` and `after`, each an object or null; `elided` only when a
    state was withheld: unique `before`/`after` names, at most 2, each of them null."""
    elided = detail.get("elided")
    assert set(detail) == {*DETAIL_STATES} | ({"elided"} if elided is not None else set())
    assert all(detail[s] is None or isinstance(detail[s], dict) for s in DETAIL_STATES)
    if elided is not None:
        assert 0 < len(elided) == len(set(elided)) <= 2 and set(elided) <= set(DETAIL_STATES)
        assert all(detail[s] is None for s in elided)


def _record(n: int, clock: FakeClock, **over: Any) -> dict[str, Any]:
    """A record with every column set; `over` replaces any of them."""
    record = {
        "record_id": f"00000000-0000-4000-8000-{n:012d}",
        "action": "orders.submit",
        "actor_user_id": str(_ACTOR),
        "actor_label": "alice",
        "actor_ip": "100.84.12.9",
        "session_id": str(_SESSION),
        "object_kind": "order",
        "object_id": f"o-{n}",
        "object_label": "BTCUSDT long",
        "outcome": "denied",
        "severity": "warning",
        "reason": "owner_only",
        "before_state": {"qty": "1"},
        "after_state": {"qty": "2"},
        "request_id": str(_REQUEST),
        "env": "demo",
        "event_ts": clock().isoformat(),
    }
    return {**record, **over}


async def _page(repo: FakeAuditRepository, **kw: Any) -> AuditPage:
    svc = AuditQueryService(repo)
    try:
        return await svc.query(**{"restrict_to_actor": None, "raw": True, **kw})
    finally:
        svc.close()


def test_entry_model_has_exactly_the_contract_fields() -> None:
    assert set(AuditEntry.model_fields) == CONTRACT_FIELDS


async def test_owner_entry_populates_every_field_from_the_row(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await repo.insert(_record(1, clock))
    [entry] = (await _page(repo)).items
    assert entry.actor_username == "alice"
    assert entry.subject_label == "BTCUSDT long"
    assert entry.reason == "owner_only"
    assert entry.environment is ExchangeEnv.DEMO
    assert entry.session_id == _SESSION
    assert entry.ip == "100.84.12.9"
    assert entry.detail == {"before": {"qty": "1"}, "after": {"qty": "2"}}
    assert entry.outcome is AuditOutcome.DENIED and entry.severity is Severity.WARNING
    assert entry.entry_hash and entry.prev_hash
    assert entry.user_agent is None  # no `audit_log` column carries it


async def test_owner_entry_with_all_null_columns(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await repo.insert(
        {
            "record_id": "00000000-0000-4000-8000-000000000002",
            "action": "system.tick",
            "actor_label": "system",
            "outcome": "success",
            "severity": "info",
            "event_ts": clock().isoformat(),
        }
    )
    [entry] = (await _page(repo)).items
    assert entry.reason is None and entry.environment is None and entry.session_id is None
    assert entry.subject_label is None and entry.ip is None
    # The contract: `detail` is "`before` and `after`, each an object or null".
    assert entry.detail == {"before": None, "after": None}


async def test_raw_reaches_the_repository_as_stated(repo: FakeAuditRepository) -> None:
    """Never inferred from the scope or from `owner`, the read-slot flag; omitted, it is
    the narrower read."""
    svc = AuditQueryService(repo)
    try:
        await svc.query(restrict_to_actor=None, owner=True)
        await svc.query(restrict_to_actor=None, raw=True)
    finally:
        svc.close()
    assert [(c["raw"], c["owner"]) for c in repo.page_calls] == [(False, True), (True, False)]


async def test_a_non_raw_read_reads_no_owner_only_column_and_builds_no_detail(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """The fake returns only a view's selected columns, so a read of an Owner-only one
    would raise. A Manager's `detail` is exactly `{}`, with no `elided`, even for a row
    whose states are over the caps."""
    await repo.insert(_record(1, clock))
    repo.over_cap.add(1)
    [entry] = (await _page(repo, restrict_to_actor=str(_ACTOR), raw=False)).items
    assert (entry.ip, entry.reason, entry.environment) == (None, None, None)
    assert (entry.session_id, entry.subject_label) == (None, None)
    assert entry.detail == {}
    assert entry.actor_username == "alice" and entry.subject_id == "o-1"


_STATE = {"qty": "1"}
_NULLS = {"before": None, "after": None}


@pytest.mark.parametrize(
    ("before", "after", "elided"),
    [(_STATE, _STATE, ["before", "after"]), (None, _STATE, ["after"]), (None, None, None)],
    ids=["both_withheld", "a_stored_null_is_never_elided", "nothing_withheld"],
)
async def test_owner_states_of_a_row_over_the_render_caps_are_withheld(
    repo: FakeAuditRepository,
    clock: FakeClock,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    elided: list[str] | None,
) -> None:
    """No complete canonical form (`chain` is `None`): only whether each state is null is
    known, so a non-null state is withheld and a null one stays null, unlisted."""
    await repo.insert(_record(1, clock, before_state=before, after_state=after))
    repo.over_cap.add(1)
    [entry] = (await _page(repo)).items
    assert entry.detail == (_NULLS if elided is None else {**_NULLS, "elided": elided})
    _assert_detail_shape(entry.detail)


@pytest.mark.parametrize(
    "rendering",
    ['{"qty": ', "[1, 2]", '"text"', "7", "1" * 5000],
    ids=["not_json", "an_array", "a_string", "a_number", "an_int_past_the_digit_limit"],
)
def test_a_rendering_that_is_not_an_object_is_withheld_never_raised_or_echoed(
    rendering: str,
) -> None:
    """Defensive: a jsonb rendering always parses, but a state that cannot be returned as
    an object is withheld rather than failing the page or returning its text."""
    detail = query_mod._owner_detail(
        {"chain": {"before_state": rendering, "after_state": '{"qty": "2"}'}}
    )
    assert detail == {"before": None, "after": {"qty": "2"}, "elided": ["before"]}
    _assert_detail_shape(detail)


def test_a_jsonb_null_rendering_is_a_null_state_not_withheld() -> None:
    detail = query_mod._owner_detail({"chain": {"before_state": "null", "after_state": None}})
    assert detail == {"before": None, "after": None}


def _nested(depth: int) -> str:
    return '{"a": ' * depth + "1" + "}" * depth


@pytest.mark.parametrize(
    ("state", "returned"),
    [
        (_nested(STATE_MAX_DEPTH), True),
        (_nested(STATE_MAX_DEPTH + 1), False),
        (json.dumps({"rows": [[i] for i in range(2 * STATE_MAX_DEPTH)]}), True),
    ],
    ids=["at_the_limit", "past_the_limit", "many_brackets_but_shallow"],
)
def test_a_state_is_withheld_only_when_nested_past_the_limit(state: str, returned: bool) -> None:
    detail = query_mod._owner_detail({"chain": {"before_state": state, "after_state": None}})
    withheld = {**_NULLS, "elided": ["before"]}
    assert detail == ({"before": json.loads(state), "after": None} if returned else withheld)
    _assert_detail_shape(detail)


async def test_a_deeply_nested_state_cannot_fail_the_owners_page(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """The response serializer refuses about 255 levels: without the depth limit this
    state would turn the whole page into a 500."""
    await repo.insert(_record(1, clock, before_state=json.loads(_nested(300))))
    page = await _page(repo)
    assert page.items[0].detail == {"before": None, "after": {"qty": "2"}, "elided": ["before"]}
    assert page.model_dump(mode="json")["items"][0]["detail"]["elided"] == ["before"]


async def test_owner_states_are_parsed_on_the_hasher_thread(
    repo: FakeAuditRepository, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    await repo.insert(_record(1, clock))
    threads: list[str] = []
    real = query_mod._parse_state

    def spy(rendering: str) -> dict[str, Any] | None:
        threads.append(threading.current_thread().name)
        return real(rendering)

    monkeypatch.setattr(query_mod, "_parse_state", spy)
    assert (await _page(repo)).items[0].detail["after"] == {"qty": "2"}
    assert len(threads) == 2 and all(t.startswith("cv-audit-hash") for t in threads)


async def test_manager_projection_blanks_everything_not_allow_listed(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await repo.insert(_record(1, clock))
    [entry] = (await _page(repo)).items
    dumped = redact_entry_for_view(entry, AuditView.OWN_REDACTED).model_dump()
    for name in CONTRACT_FIELDS - OWN_REDACTED_FIELDS:
        assert dumped[name] == ({} if name == "detail" else None), name
    assert dumped["actor_username"] == "alice" and dumped["action"] == "orders.submit"
    assert dumped["subject_id"] == "o-1" and dumped["request_id"] == str(_REQUEST)


def test_allow_list_names_only_contract_fields() -> None:
    assert OWN_REDACTED_FIELDS <= CONTRACT_FIELDS


async def test_owner_json_round_trips_state(repo: FakeAuditRepository, clock: FakeClock) -> None:
    await repo.insert(_record(1, clock))
    [entry] = (await _page(repo)).items
    assert json.loads(entry.model_dump_json())["detail"]["after"] == {"qty": "2"}


# ---- Security review finding 3: the served JSON, through the real query service -----------


class _Writer:
    async def emit(self, action: str, **_: Any) -> None:
        """The read records the router writes are not under test here."""


class _Service:
    """The router's `AuditServiceLike` over the real `AuditQueryService`."""

    is_active = True

    def __init__(self, query: AuditQueryService) -> None:
        self.query, self.writer = query, _Writer()


class _Resolver:
    def __init__(self, principal: AuditPrincipal) -> None:
        self.principal = principal

    async def resolve(self, request: Request) -> AuditPrincipal:
        return self.principal


async def _served(repo: FakeAuditRepository, principal: AuditPrincipal) -> dict[str, Any]:
    svc = AuditQueryService(repo)
    app = FastAPI()
    app.include_router(make_audit_router(_Service(svc), _Resolver(principal)))
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            response = await client.get("/admin/audit")
    finally:
        svc.close()
    assert response.status_code == 200
    [item] = response.json()["items"]
    assert isinstance(item, dict)
    return item


async def test_the_router_serves_the_owner_every_field_and_a_manager_the_allow_list(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """One fully populated row, read by the Owner and by the Manager who is its actor."""
    await repo.insert(_record(1, clock))
    owner = AuditPrincipal(
        user_id=uuid.uuid4(), username="owner", permissions=frozenset({"audit:read"}), is_owner=True
    )
    manager = AuditPrincipal(
        user_id=_ACTOR, username="alice", permissions=frozenset({"audit:read"})
    )
    owner_json, manager_json = await _served(repo, owner), await _served(repo, manager)
    assert [call["raw"] for call in repo.page_calls] == [True, False]
    assert set(owner_json) == set(manager_json) == CONTRACT_FIELDS
    assert {k for k, v in owner_json.items() if v is None} == {"user_agent"}  # no column
    assert owner_json["detail"] == {"before": {"qty": "1"}, "after": {"qty": "2"}}
    _assert_detail_shape(owner_json["detail"])
    hidden = CONTRACT_FIELDS - OWN_REDACTED_FIELDS
    assert {k for k, v in manager_json.items() if v is None} == hidden - {"detail"}
    assert manager_json["detail"] == {}
    assert manager_json["entry_hash"] is None and manager_json["prev_hash"] is None
