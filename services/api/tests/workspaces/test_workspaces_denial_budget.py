"""#5435: the read paths' `rbac.denied` records are budgeted per acting user (`DenialBudget`).

A foreign id is always the same 404; only its audit record is budgeted, with the bound the alert
deliveries ship (`DENIALS_PER_WINDOW` per `DENIAL_WINDOW_S`). Past it a denial is counted, not
written, and the caller's next record carries the count. A write's denial is always recorded.
No sleep: the budget's clock is fake.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.api.alert_deliveries import DENIAL_WINDOW_S, DENIALS_PER_WINDOW, DenialBudget
from tests.workspaces._workspaces_api_env import USER_A, USER_B, Env, wire


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _foreign(env: Env) -> tuple[str, str]:
    """A live workspace of `USER_B`'s with one layout; the caller is `USER_A` again after."""
    env.as_user(USER_B)
    wid = env.create()["id"]
    lid = env.make_layout(wid)["id"]
    env.as_user(USER_A)
    return wid, lid


def _not_found(r: Any) -> bool:
    return bool(r.status_code == 404 and r.json()["code"] == "not_found")


def test_get_workspace_foreign_id_past_the_budget_stays_404_records_once_per_window() -> None:
    """The shipped bound: within one window every probe answers 404 and exactly
    `DENIALS_PER_WINDOW` records are written; once the window rolls over the next probe is
    recorded again, carrying the count the budget held back."""
    clock = _Clock()
    env = Env(denials=DenialBudget(clock=clock))
    wid, _ = _foreign(env)
    extra = 5
    for _ in range(DENIALS_PER_WINDOW + extra):
        assert _not_found(env.c.get(f"/workspaces/{wid}"))
    denied = env.audit.denied()
    assert len(denied) == DENIALS_PER_WINDOW
    assert all("after_state" not in d for d in denied)
    assert {(d["object_kind"], d["object_id"], d["reason"]) for d in denied} == {
        ("workspace", wid, "not_owner:workspaces:read:self")
    }
    clock.t += DENIAL_WINDOW_S - 1  # still inside the window: nothing more is written
    assert _not_found(env.c.get(f"/workspaces/{wid}"))
    assert len(env.audit.denied()) == DENIALS_PER_WINDOW
    clock.t += 1  # the window rolls over: one more record, carrying the held count
    assert _not_found(env.c.get(f"/workspaces/{wid}"))
    after = env.audit.denied()
    assert len(after) == DENIALS_PER_WINDOW + 1
    assert after[-1]["after_state"] == {"suppressed_before": extra + 1}


def test_router_default_denial_budget_uses_the_shipped_bound() -> None:
    """No budget passed: the router builds its own with the shipped bound."""
    env = Env()
    wid, _ = _foreign(env)
    for _ in range(DENIALS_PER_WINDOW + 3):
        assert _not_found(env.c.get(f"/workspaces/{wid}"))
    assert len(env.audit.denied()) == DENIALS_PER_WINDOW


@pytest.mark.parametrize("route", ["workspace", "layouts", "layout"])
def test_read_routes_foreign_id_spend_one_shared_budget(route: str) -> None:
    """Every read route's foreign-id denial spends the same caller's budget."""
    env = Env(denials=DenialBudget(per_window=1, window_s=60, clock=_Clock()))
    wid, lid = _foreign(env)
    path = {
        "workspace": f"/workspaces/{wid}",
        "layouts": f"/workspaces/{wid}/layouts",
        "layout": f"/workspaces/{wid}/layouts/{lid}",
    }[route]
    for _ in range(3):
        assert _not_found(env.c.get(path))
    assert len(env.audit.denied()) == 1
    assert _not_found(env.c.get(f"/workspaces/{wid}"))  # another read: same budget, held
    assert len(env.audit.denied()) == 1


def test_read_denial_budget_is_per_acting_user() -> None:
    """One caller's spent budget does not hold back another caller's record."""
    env = Env(denials=DenialBudget(per_window=1, window_s=60, clock=_Clock()))
    theirs, _ = _foreign(env)  # USER_B's
    own = env.create("Mine")["id"]  # USER_A's
    for _ in range(2):
        assert _not_found(env.c.get(f"/workspaces/{theirs}"))
    env.as_user(USER_B)
    assert _not_found(env.c.get(f"/workspaces/{own}"))
    assert [d["actor_user_id"] for d in env.audit.denied()] == [USER_A, USER_B]


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_write_denials_are_recorded_past_an_exhausted_read_budget(method: str) -> None:
    """The budget is the read paths': a foreign-id write is recorded every time."""
    env = Env(denials=DenialBudget(per_window=1, window_s=60, clock=_Clock()))
    wid, _ = _foreign(env)
    for _ in range(2):
        assert _not_found(env.c.get(f"/workspaces/{wid}"))
    for _ in range(2):
        r = env.c.request(method, f"/workspaces/{wid}", json=wire({"name": "x"}))
        assert _not_found(r)
    reasons = [d["reason"] for d in env.audit.denied()]
    assert reasons == ["not_owner:workspaces:read:self"] + ["not_owner:workspaces:write:self"] * 2


def test_read_denial_whose_record_fails_keeps_its_slot_and_its_count() -> None:
    """A failed write gives back what `admit` took: the next record still carries the count."""
    env = Env(denials=DenialBudget(per_window=1, window_s=60, clock=_Clock()))
    wid, _ = _foreign(env)

    async def refuse(action: str, **kw: object) -> None:
        raise RuntimeError("audit writer down")

    real, env.audit.emit = env.audit.emit, refuse  # type: ignore[method-assign]  # fault injection
    with pytest.raises(RuntimeError, match="audit writer down"):
        env.c.get(f"/workspaces/{wid}")
    env.audit.emit = real  # type: ignore[method-assign]  # fault injection
    assert _not_found(env.c.get(f"/workspaces/{wid}"))
    (denial,) = env.audit.denied()  # the slot came back: written, carrying the failed one
    assert denial["after_state"] == {"suppressed_before": 1}
