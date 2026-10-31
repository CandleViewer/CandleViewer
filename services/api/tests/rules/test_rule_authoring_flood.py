"""#4834 (E35 authoring limits, G-2): a flood of refused rule checks and writes, end to end.

The validate / compile limit throttles the checks, and the records the admitted refusals leave are
held to the refusal-record budget: past `rules_refusal_budget_per_hour` a refusal keeps its own
answer and is counted and carried, never recorded (22 "Rule authoring refusal records"); a due
record that cannot be written is `503 audit_unavailable` and nothing changes. The first test is the
server leg of E36-X02's AC-RA-17 (a validate flood) for its suite to import. One fake clock drives
the limiter and the budget; nothing sleeps.
"""

from __future__ import annotations

import inspect
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.admin.wiring import audit_writer_sink
from candleviewer.api.preview_limiter import PreviewLimiter
from candleviewer.api.rules import make_rules_router
from candleviewer.api.rules_actor import make_rules_audit
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.api.rules_refusals import ARM, SCOPE_DENIED, RuleRefusalBudgets
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RulesManager
from candleviewer.rules.service import RulesService
from candleviewer.rules.vocabulary import default_registry
from candleviewer.settings import RULES_REFUSAL_BUDGET_PER_HOUR
from tests.rules.test_rule_check_limit import BURST, RATE, _Resolver
from tests.rules.test_rules_routes import BASE, _ir
from tests.rules.test_scope_crud import A as GRANTED
from tests.rules.test_scope_crud import C as UNGRANTED
from tests.rules.test_scope_crud import _Src
from tests.unit.api.test_audit_budget import _Clock, _Writer

CAP = RULES_REFUSAL_BUDGET_PER_HOUR
REG = default_registry()
OWNER_ID, MANAGER_ID = UUID(int=1), UUID(int=2)
FOREIGN = {"level": "account", "account_ids": [str(UNGRANTED)]}


class _Stack:
    """The checks behind the limiter and the write routes over one manager, both writers of the
    refusal records on one budget, one fake clock for the limiter and the budget. Who calls is
    in the headers: `x-user` (a UUID) and `x-owner` (`1` for the Owner)."""

    def __init__(self, per_hour: int = CAP, **budget: Any) -> None:
        self.clock = _Clock()
        self.clock.now = 1000.0
        self.writer = _Writer(self.clock)
        self.suppressed = 0
        self.limited: list[str] = []
        self.budgets = RuleRefusalBudgets(
            self.writer, per_hour=per_hour, clock=self.clock, on_suppressed=self._count, **budget
        )
        service = RulesService()
        service.wire_scope(
            _Src(), "demo", audit_writer_sink(self.writer, acting=str, refusals=self.budgets)
        )
        checks = make_rules_router(
            lambda: REG,
            principal_resolver=_Resolver(),
            check_limiter=PreviewLimiter(RATE, burst=BURST, clock=self.clock),
            on_rate_limited=self.limited.append,
            scope_resolver=service.scope_resolver,
            scope_refresh=service.refresh_scope,
        )
        audit = make_rules_audit(self.writer, refusals=self.budgets)
        self.mgr = RulesManager(InMemoryRuleStore(), REG, audit=audit)

        def actor(request: Request) -> Actor:
            user, owner = request.headers["x-user"], request.headers.get("x-owner") == "1"
            granted = frozenset({str(GRANTED)})  # what the resolver's source grants too
            return Actor(user, "s", frozenset(BASE), granted, is_owner=owner, step_up_fresh=True)

        writes = make_rules_crud_router(
            lambda: self.mgr,
            actor,
            scope_resolver=lambda: service.scope_resolver,
            scope_refresh=service.refresh_scope,
        )
        app = FastAPI()
        app.include_router(checks)
        app.include_router(writes)
        self.c = TestClient(app)

    def _count(self) -> None:
        self.suppressed += 1

    def validate(self, user: UUID = MANAGER_ID) -> Any:
        sent = {"x-user": str(user)}
        return self.c.post("/rules/validate", json={"ir": _ir(scope=FOREIGN)}, headers=sent)

    def as_user(self, user: UUID, owner: bool = False) -> dict[str, str]:
        return {"x-user": str(user), "x-owner": "1" if owner else "0"}

    def records(self, action: str, user: UUID = MANAGER_ID) -> list[dict[str, Any]]:
        return [
            kw
            for a, kw, _ in self.writer.records
            if a == action and kw["actor_user_id"] == str(user)
        ]


def test_a_validate_flood_with_scope_refusals_is_throttled_and_its_records_are_budgeted() -> None:
    """AC-RA-17's server leg: a validate flood naming an ungranted account. The limit admits the
    burst and then its rate; each admitted call is the scope's `403`, recorded up to the cap and
    then counted; a throttled call is `429` and writes nothing."""
    s = _Stack()
    first = [s.validate() for _ in range(BURST + 5)]
    assert [r.status_code for r in first] == [403] * BURST + [429] * 5
    admitted, throttled = BURST, 5
    while admitted <= CAP + 9:  # a second at a time, at the rate
        s.clock.now += 1.0
        answers = [s.validate().status_code for _ in range(RATE + 2)]
        assert answers == [403] * RATE + [429] * 2
        admitted, throttled = admitted + RATE, throttled + 2
    assert len(s.records(SCOPE_DENIED)) == CAP == len(s.writer.records)  # a 429 writes nothing
    assert (s.suppressed, len(s.limited)) == (admitted - CAP, throttled)
    s.clock.now += 3600.0  # the hour has rolled: the next record carries the count
    assert s.validate().status_code == 403
    assert s.records(SCOPE_DENIED)[-1]["after_state"]["suppressed"] == admitted - CAP


def test_the_refusal_is_still_answered_403_or_404_over_the_cap() -> None:
    """Over the cap a refusal keeps its own status: the scope's `403` (the resolver's record) and
    another user's rule's `404` (the manager's record), one budget for both."""
    s = _Stack(per_hour=2)
    owner = s.as_user(OWNER_ID, owner=True)
    rid = s.c.post("/rules", json={"ir": _ir()}, headers=owner).json()["id"]
    manager = s.as_user(MANAGER_ID)
    for _ in range(3):
        put = s.c.put(f"/rules/{rid}", json={"ir": _ir("2")}, headers=manager | {"If-Match": "1"})
        assert (put.status_code, put.json()["code"]) == (404, "not_found")
        made = s.c.post("/rules", json={"ir": _ir(name="x", scope=FOREIGN)}, headers=manager)
        assert (made.status_code, made.json()["code"]) == (403, "forbidden")
    assert len(s.records(SCOPE_DENIED)) == 2 and s.suppressed == 4
    assert [v.version for v in s.mgr._s._rows[rid].versions] == [1]  # type: ignore[attr-defined]


def test_the_owner_and_a_manager_share_the_same_cap() -> None:
    """One cap for every role: the Owner's refused arms are capped exactly as a Manager's are."""
    s = _Stack(per_hour=2)
    for user, owner in ((OWNER_ID, True), (MANAGER_ID, False)):
        who = s.as_user(user, owner)
        rid = s.c.post("/rules", json={"ir": _ir(name=f"r{user.int}")}, headers=who).json()["id"]
        for n in range(3):  # arming a rule never simulated: refused, `rules.arm`
            sent = who | {"Idempotency-Key": f"k{n}"}
            r = s.c.put(f"/rules/{rid}/mode", json={"mode": "armed"}, headers=sent)
            assert r.status_code == 422, r.text
        assert len(s.records(ARM, user)) == 2
    assert s.suppressed == 2


@pytest.mark.parametrize("cause", ["writer", "untracked"])
def test_a_due_record_that_cannot_be_written_is_503_audit_unavailable_and_stores_nothing(
    cause: str,
) -> None:
    """Both catch sites of the scope's record (validate, a save) and the manager's own refusals
    (another user's rule, a refused arm) answer `503 audit_unavailable` and change nothing, when
    the writer fails or when the budget cannot track the user."""
    s = _Stack(per_hour=5, tracked_users=1)
    owner = s.as_user(OWNER_ID, owner=True)
    rid = s.c.post("/rules", json={"ir": _ir()}, headers=owner).json()["id"]
    if cause == "writer":
        s.writer.mode = "fail"
    else:  # the one entry the budget tracks is busy for the hour: nobody else is tracked
        assert s.validate(OWNER_ID).status_code == 403
    manager = s.as_user(MANAGER_ID)
    answers = [
        s.validate(),
        s.c.post("/rules", json={"ir": _ir(name="x", scope=FOREIGN)}, headers=manager),
        s.c.put(f"/rules/{rid}", json={"ir": _ir("2")}, headers=manager | {"If-Match": "1"}),
        s.c.delete(f"/rules/{rid}", headers=manager),
        s.c.put(
            f"/rules/{rid}/mode",
            json={"mode": "simulate"},
            headers=manager | {"Idempotency-Key": "k"},
        ),
    ]
    assert [(r.status_code, r.json()["code"]) for r in answers] == [(503, "audit_unavailable")] * 5
    row = s.mgr._s._rows[rid]  # type: ignore[attr-defined]
    assert (len(row.versions), row.mode, row.deleted) == (1, "disabled", False)
    assert [kw for _, kw, _ in s.writer.records if kw["actor_user_id"] == str(MANAGER_ID)] == []


def test_a_refused_arm_whose_record_cannot_be_written_is_503_and_stays_disarmed() -> None:
    """The manager's mode refusal (`rules.arm`): its due record unwritable, the refusal is `503`."""
    s = _Stack(per_hour=5)
    owner = s.as_user(OWNER_ID, owner=True)
    rid = s.c.post("/rules", json={"ir": _ir()}, headers=owner).json()["id"]
    s.writer.mode = "fail"
    r = s.c.put(
        f"/rules/{rid}/mode", json={"mode": "armed"}, headers=owner | {"Idempotency-Key": "k"}
    )
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert s.mgr._s._rows[rid].mode == "disabled"  # type: ignore[attr-defined]


@pytest.mark.parametrize("cause", ["writer", "untracked"])
def test_a_protected_rules_refusal_whose_record_cannot_be_written_is_503_and_stays_armed(
    cause: str,
) -> None:
    """The system-rule refusals (`rules.scope_denied`): a change to a protected built-in whose due
    record cannot be written is `503 audit_unavailable`, and the built-in stays as it was."""
    s = _Stack(per_hour=5, tracked_users=1)
    owner = s.as_user(OWNER_ID, owner=True)
    rid = s.c.post("/rules", json={"ir": _ir(name="seed")}, headers=owner).json()["id"]
    row = s.mgr._s._rows[rid]  # type: ignore[attr-defined]
    row.name, row.mode = "sys.native_sl_watchdog", "armed"  # as the provisioner would
    if cause == "writer":
        s.writer.mode = "fail"
    else:  # the one entry the budget tracks is busy for the hour: the Owner is not tracked
        assert s.validate(MANAGER_ID).status_code == 403
    answers = [
        s.c.put(
            f"/rules/{rid}/mode",
            json={"mode": "disabled"},
            headers=owner | {"Idempotency-Key": "k"},
        ),
        s.c.delete(f"/rules/{rid}", headers=owner),
        s.c.put(
            f"/rules/{rid}", json={"ir": _ir(name=row.name)}, headers=owner | {"If-Match": "1"}
        ),
        s.c.put(
            f"/rules/{rid}/active-version",
            json={"version_id": row.versions[0].id},
            headers=owner,
        ),
    ]
    assert [(r.status_code, r.json()["code"]) for r in answers] == [(503, "audit_unavailable")] * 4
    assert (row.mode, row.deleted, len(row.versions)) == ("armed", False, 1)


def test_the_checks_are_never_built_without_their_limit() -> None:
    """The validate / compile limit is a required argument of the checks' router, so no router is
    built unlimited, the app's and every test rig's alike."""
    limiter = inspect.signature(make_rules_router).parameters["check_limiter"]
    assert limiter.default is inspect.Parameter.empty
    assert limiter.kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(TypeError):
        make_rules_router(lambda: REG)  # type: ignore[call-arg]  # the refusal under test
