"""#2626 (04 §7.3, SR-067): a Manager's refused write leaves the same trace for a rule outside their
scope as for a missing or a deleted one: one `rule.scope_refused` record (`rules.scope_denied`),
awaited ahead of the same 404. The own view runs the real audit path: the rules hook over a started
`AuditWriter`, read back and projected as `api/audit.py` serves a non-Owner's page. The plain reads
are in `tests/rules/test_rule_ownership.py`.
"""

from __future__ import annotations

import asyncio
import copy
import statistics
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from candleviewer.api.rules_actor import make_rules_audit
from candleviewer.audit.access import AuditView, redact_entry_for_view
from candleviewer.audit.models import AuditEntry, AuditOutcome
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditUnavailable, AuditWriter
from candleviewer.rules.manager import (
    Actor,
    GrantRead,
    InMemoryRuleStore,
    RuleError,
    RuleRefusalUnrecorded,
    RulesManager,
)
from candleviewer.rules.vocabulary import default_registry
from tests.contract.rbac.rbac_harness import (
    FOREIGN,
    GRANTED,
    RecordingRuleStore,
    World,
    actor_grants,
    bearer,
    user_id_of,
)
from tests.rules.test_rule_ownership import _ROUTES
from tests.rules.test_rules_routes import _ir
from tests.unit.audit.audit_fakes import FakeAuditRepository, FakeClock

GUARD_S = 5.0  # a wait's bound: only a regression reaches it
MISSING = str(uuid.uuid5(uuid.NAMESPACE_URL, "cv-2626/missing"))  # no store holds it
CASES = ("hidden", "missing", "deleted")


def _actor(name: str, *granted: uuid.UUID) -> Actor:
    perms = frozenset({"rules:read", "rules:write"})
    return Actor(str(user_id_of(name)), name, perms, frozenset(map(str, granted)), name == "owner")


OWNER = _actor("owner")
#: Each Manager, with the account of the Owner's rule they cannot reach (#3334).
MANAGERS = {
    "manager_with_grant": (_actor("manager_with_grant", GRANTED), FOREIGN),
    "manager_without_grant": (_actor("manager_without_grant"), GRANTED),
}
#: Each write route's first look at the stored rule, as `api/rules_crud.py` takes it, called with
#: the rule id and a version id; `PUT /rules/{id}/mode` arms through its pre-check.
WRITES: dict[str, Callable[[RulesManager, str, str, Actor], Awaitable[object]]] = {
    "PUT /rules/{id}": lambda m, rid, _v, a: m.require_visible(rid, a, "update"),
    "DELETE /rules/{id}": lambda m, rid, _v, a: m.delete(rid, a),
    "PUT /rules/{id}/active-version": lambda m, rid, vid, a: m.visible_version(
        rid, vid, a, "set_active_version"
    ),
    "PUT /rules/{id}/mode simulate": lambda m, rid, _v, a: m.set_mode(rid, "simulate", a, "k"),
    "PUT /rules/{id}/mode armed": lambda m, rid, _v, a: m.active_scope(rid, a, "set_mode"),
}
HTTP = [route for route, spec in _ROUTES.items() if spec[3]]  # the routes that write
#: KV-I13's rules (`test_scope_and_ws.py`): `x-correlation-id` is minted per request and `date` is
#: the server clock; two medians both under the floor pass whatever their ratio.
_PER_REQUEST_HEADERS = frozenset({"x-correlation-id", "date"})
_TIMING_FLOOR_S = 0.05
_WRITE = pytest.mark.parametrize("route", WRITES)


@dataclass
class _Asked:
    """What the calls on one rule left: the last answer, the time each took, the refusal records
    written and the store reads made."""

    answer: Any = None
    times: list[float] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    reads: list[Any] = field(default_factory=list)


class _Trail:
    """The real audit path, read back as `GET /admin/audit` reads it (`api/audit.py`)."""

    def __init__(self, tmp_path: Path) -> None:
        repo = FakeAuditRepository()
        wal = str(tmp_path / "audit.wal")
        self.writer = AuditWriter(repo, wal, clock=FakeClock(), sleep=repo.retry_sleep)
        self.query = AuditQueryService(repo)

    async def __aenter__(self) -> _Trail:
        await self.writer.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.writer.stop(1)
        self.query.close()

    async def view(self, user_id: str | None) -> list[AuditEntry]:
        """Newest first: the Owner's raw view (`None`), else the user's own, scoped, projected."""
        await self.writer.flush(GUARD_S)
        page = await self.query.query(restrict_to_actor=user_id, raw=user_id is None)
        if user_id is None:
            return list(page.items)
        return [redact_entry_for_view(e, AuditView.OWN_REDACTED) for e in page.items]


async def _cases(m: RulesManager, account: uuid.UUID) -> tuple[dict[str, str], str]:
    """The ids a refused write names: the Owner's rule on `account`, one no store holds and the
    Owner's rule deleted; with the first one's version id, which every call names."""
    scope = {"level": "account", "account_ids": [str(account)]}
    hidden = await m.create(_ir(name="hidden", scope=scope), OWNER)
    gone = await m.create(_ir(name="gone", scope=scope), OWNER)
    await m.delete(str(gone["id"]), OWNER)
    ids = {"hidden": str(hidden["id"]), "missing": MISSING, "deleted": str(gone["id"])}
    return ids, str(hidden["version"]["id"])


@_WRITE
@pytest.mark.parametrize("manager", MANAGERS)
async def test_own_view_of_a_refused_write_is_the_same_for_a_hidden_a_missing_and_a_deleted_rule(
    tmp_path: Path, route: str, manager: str
) -> None:
    """AC-1: each refused write leaves the Manager's own view one row; leaving out `id`, `ts`,
    `request_id` and the id asked for, the three rows are equal."""
    actor, account = MANAGERS[manager]
    rows: list[AuditEntry] = []
    async with _Trail(tmp_path) as trail:
        m = RulesManager(
            InMemoryRuleStore(), default_registry(), audit=make_rules_audit(trail.writer)
        )
        ids, vid = await _cases(m, account)
        for case in CASES:
            with pytest.raises(RuleError) as refused:
                await WRITES[route](m, ids[case], vid, actor)
            assert (refused.value.status, refused.value.code) == (404, "not_found")
            own = await trail.view(actor.user_id)
            assert len(own) == len(rows) + 1, f"{case}: one row in the own view per refused write"
            rows.append(own[0])
    assert [(r.subject_type, r.subject_id) for r in rows] == [("rule", ids[c]) for c in CASES]
    assert {(r.action, r.outcome) for r in rows} == {("rules.scope_denied", AuditOutcome.DENIED)}
    alike = [r.model_dump(exclude={"id", "ts", "request_id", "subject_id"}) for r in rows]
    assert alike[0] == alike[1] == alike[2]


async def test_owner_view_keeps_the_full_refusal_row_for_a_hidden_and_a_missing_rule(
    tmp_path: Path,
) -> None:
    """AC-2: the Owner's raw view keeps both refusals whole; the Manager's projection of the same
    rows holds no detail."""
    actor, account = MANAGERS["manager_with_grant"]
    async with _Trail(tmp_path) as trail:
        m = RulesManager(
            InMemoryRuleStore(), default_registry(), audit=make_rules_audit(trail.writer)
        )
        ids, _ = await _cases(m, account)
        for case in ("hidden", "missing"):
            with pytest.raises(RuleError):
                await m.delete(ids[case], actor)
        raw = [e for e in await trail.view(None) if e.action == "rules.scope_denied"]
        own = await trail.view(actor.user_id)
    asked = [ids["missing"], ids["hidden"]]
    assert [e.subject_id for e in raw] == asked == [e.subject_id for e in own]
    for e in raw:
        assert (e.actor_user_id, e.outcome) == (uuid.UUID(actor.user_id), AuditOutcome.DENIED)
        after = {"rule_id": e.subject_id, "op": "delete", "reason": "rule_not_visible"}
        assert e.detail == {"before": None, "after": after | {"event": "rule.scope_refused"}}
    assert [e.detail for e in own] == [{}, {}]


def _owners_rule(world: World, account: uuid.UUID, name: str) -> tuple[str, str]:
    """The Owner's rule `name` on `account`, outside both Managers' scope: its id and its version
    id."""
    body = {"ir": _ir(name=name, scope={"level": "account", "account_ids": [str(account)]})}
    made = world.client.post("/rules", json=body, headers=bearer("owner"))
    assert made.status_code == 201, made.text
    return str(made.json()["id"]), str(made.json()["version"]["id"])


def _owners_cases(world: World, account: uuid.UUID) -> tuple[dict[str, str], str]:
    """`_cases` over HTTP: the ids a refused write names by case, with the first rule's version
    id, which every call names."""
    hidden, vid = _owners_rule(world, account, "hidden")
    gone, _ = _owners_rule(world, account, "gone")
    removed = world.client.delete(f"/rules/{gone}", headers=bearer("owner"))
    assert removed.status_code == 204, removed.text
    return {"hidden": hidden, "missing": MISSING, "deleted": gone}, vid


@pytest.mark.parametrize("route", HTTP)
@pytest.mark.parametrize(
    ("actor", "account"), [("manager_with_grant", FOREIGN), ("manager_without_grant", GRANTED)]
)
def test_a_write_on_an_unseen_rule_and_on_a_missing_one_answer_identically_and_both_are_recorded(
    world: World, route: str, actor: str, account: uuid.UUID
) -> None:
    """AC-3a (KV-I13's rules): equal status, body (byte for byte) and headers but the per-request
    ones, for a rule outside the caller's scope, a missing one and a deleted one; each call is one
    read in the caller's scope that returns nothing, never a read by id, and one
    `rule.scope_refused`, alike but for the id asked for; medians of five within 10x, or all under
    50 ms (a loose bound)."""
    ids, vid = _owners_cases(world, account)
    method, path, body, op = _ROUTES[route]
    headers = {**bearer(actor), "Idempotency-Key": "k"}
    asked = {case: _Asked() for case in CASES}
    for _ in range(5):  # a round asks each case in turn, so a burst of load reaches all three
        for case, a in asked.items():
            logged, looked = len(world.audit.records), len(world.rule_store.reads)
            url = path.format(rid=ids[case], vid=vid)
            started = time.perf_counter()
            a.answer = world.client.request(method, url, json=body(vid), headers=headers)
            a.times.append(time.perf_counter() - started)
            fresh = world.audit.records[logged:]
            a.records += [r for r in fresh if r["action"] == "rule.scope_refused"]
            a.reads += world.rule_store.reads[looked:]
    for case, a in asked.items():
        assert (a.answer.status_code, a.answer.json()["code"]) == (404, "not_found"), a.answer.text
        named = [r.pop("rule_id") for r in a.records]
        assert named == [ids[case]] * 5, f"{case}: one record per refused write"
    hidden, missing, deleted = asked.values()
    assert hidden.answer.status_code == missing.answer.status_code == deleted.answer.status_code
    contents = (hidden.answer.content, missing.answer.content, deleted.answer.content)
    assert contents[0] == contents[1] == contents[2], "the body is an existence oracle"
    heads = [
        {k: v for k, v in a.answer.headers.items() if k not in _PER_REQUEST_HEADERS}
        for a in asked.values()
    ]
    assert heads[0] == heads[1] == heads[2]
    who = str(user_id_of(actor))
    refusal = {"action": "rule.scope_refused", "op": op, "reason": "rule_not_visible", "actor": who}
    assert hidden.records == missing.records == deleted.records == [refusal] * 5
    scope = GrantRead(who, frozenset(str(a) for a in actor_grants(actor)))
    assert hidden.reads == missing.reads == deleted.reads == [("scoped_page", scope, ())] * 5
    medians = [statistics.median(a.times) for a in asked.values()]
    fast = max(medians) < _TIMING_FLOOR_S
    assert fast or max(medians) < 10 * min(medians), f"timing differs by over 10x: {medians}"


@_WRITE
async def test_a_refused_write_waits_for_its_record_whether_or_not_the_rule_exists(
    route: str,
) -> None:
    """AC-3b: a hook that holds the record keeps each refused call pending until it lets go. No
    sleeps: an `entered` / `release` pair of events."""
    entered, release = asyncio.Event(), asyncio.Event()

    async def gated(action: str, payload: dict[str, Any]) -> None:
        if action == "rule.scope_refused":
            entered.set()
            await release.wait()

    m = RulesManager(InMemoryRuleStore(), default_registry(), audit=gated)
    actor, account = MANAGERS["manager_with_grant"]
    ids, vid = await _cases(m, account)
    for case in CASES:
        entered.clear()
        release.clear()
        call = asyncio.ensure_future(WRITES[route](m, ids[case], vid, actor))
        waiting = asyncio.ensure_future(entered.wait())
        try:
            async with asyncio.timeout(GUARD_S):
                await asyncio.wait({call, waiting}, return_when=asyncio.FIRST_COMPLETED)
            assert entered.is_set() and not call.done(), f"{case}: answered ahead of its record"
            release.set()
            with pytest.raises(RuleError) as refused:
                async with asyncio.timeout(GUARD_S):
                    await call
            assert (refused.value.status, refused.value.code) == (404, "not_found")
        finally:
            call.cancel()
            waiting.cancel()


async def _unwritable(action: str, payload: dict[str, Any]) -> None:
    if action == "rule.scope_refused":
        raise AuditUnavailable("the audit store is down")


@_WRITE
async def test_an_unrecorded_refusal_answers_a_hidden_and_a_missing_rule_alike(route: str) -> None:
    """AC-4 (chaos scenario 10, C-13.6): a refusal whose record cannot be written is
    `RuleRefusalUnrecorded` with the same cause for a rule outside the caller's scope, a missing
    one and a deleted one, and nothing changes. The hook fails at once, so no bound is waited
    out."""
    store = InMemoryRuleStore()
    m = RulesManager(store, default_registry(), audit=_unwritable)
    actor, account = MANAGERS["manager_with_grant"]
    ids, vid = await _cases(m, account)
    before = copy.deepcopy(store._rows)
    causes = []
    for case in CASES:
        with pytest.raises(RuleRefusalUnrecorded) as lost:
            await WRITES[route](m, ids[case], vid, actor)
        causes.append(type(lost.value.__cause__))
    assert causes == [AuditUnavailable] * 3
    assert store._rows == before


@pytest.mark.parametrize("route", HTTP)
def test_an_unrecorded_refusal_answers_a_hidden_and_a_missing_rule_alike_over_http(
    world: World, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """AC-4 over HTTP: the three answers are equal, status and body, each a `503
    audit_unavailable` on every write route, and nothing changes."""
    ids, vid = _owners_cases(world, FOREIGN)
    kept = copy.deepcopy(world.rule_store._rows)
    sink = world.audit.emit

    async def emit(action: str, **fields: Any) -> None:
        await _unwritable(action, fields)
        await sink(action, **fields)

    monkeypatch.setattr(world.audit, "emit", emit)
    method, path, body, _ = _ROUTES[route]
    headers = {**bearer("manager_with_grant"), "Idempotency-Key": "k"}
    answers = [
        world.client.request(
            method, path.format(rid=ids[case], vid=vid), json=body(vid), headers=headers
        )
        for case in CASES
    ]
    assert [a.status_code for a in answers] == [503] * 3
    assert answers[0].json()["code"] == "audit_unavailable"
    assert answers[0].content == answers[1].content == answers[2].content
    assert world.rule_store._rows == kept


@_WRITE
async def test_owner_write_on_a_missing_or_deleted_rule_is_a_404_with_no_record(
    route: str,
) -> None:
    """AC-5 (BQ-3): no rule is hidden from the Owner role, so its miss is a missing or a deleted
    rule: read by id, answered 404, and recorded as no refusal."""
    audits: list[str] = []

    async def audit(action: str, payload: dict[str, Any]) -> None:
        audits.append(action)

    store = RecordingRuleStore()
    m = RulesManager(store, default_registry(), audit=audit)
    ids, vid = await _cases(m, GRANTED)
    store.reads.clear()
    for case in ("missing", "deleted"):
        with pytest.raises(RuleError) as refused:
            await WRITES[route](m, ids[case], vid, OWNER)
        assert (refused.value.status, refused.value.code) == (404, "not_found")
    assert "rule.scope_refused" not in audits
    assert [(method, scope) for method, scope, _ in store.reads] == [("get", None)] * 2
