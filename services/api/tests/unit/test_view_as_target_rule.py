"""#3085: the start route and the eligibility port answer from one target rule
(`auth.scopes.unviewable_target`): the viewable statuses and the Owner test. Each test changes the
rule where it lives and sees both sides follow, so neither keeps a copy of it, and a context starts
only for a target that its next evaluation keeps."""

from __future__ import annotations

import pytest

from candleviewer.auth import scopes
from candleviewer.auth.models import UserStatus
from candleviewer.view_as_wiring import IdentityEligibility
from tests.unit.admin.test_view_as_service import _TARGET, _VIEWER
from tests.unit.api.test_view_as_start_route import World, _user
from tests.unit.auth.test_step_up import _session
from tests.unit.test_view_as_wiring import _WRITE, _Identity


async def _the_start_lets_through(status: str, roles: tuple[str, ...]) -> bool:
    """Whether the start route starts a context on a target of *status* and *roles*."""
    w = World()
    await w.sign_in()
    w.users.rows[str(_TARGET)] = _user("bo", status=status, roles=roles)
    return (await w.start()).status_code == 201


async def _the_port_keeps(status: str, roles: list[str]) -> bool:
    """Whether the eligibility port keeps a context on a target of *status* and *roles*."""
    port = IdentityEligibility(_Identity({"status": status, "roles": roles}, _WRITE))
    return await port.ineligible(_session(_VIEWER), _TARGET) is None


@pytest.mark.parametrize("status", [s.value for s in UserStatus])
async def test_the_start_and_the_eligibility_port_read_the_viewable_statuses_from_one_list(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    """Only `invited` is viewable once the list says so: it alone starts and stays."""
    monkeypatch.setattr(scopes, "VIEWABLE_STATUSES", frozenset({"invited"}))
    starts = await _the_start_lets_through(status, ("manager",))
    assert starts == await _the_port_keeps(status, ["manager"]) == (status == "invited")


@pytest.mark.parametrize("role", ["owner", "manager", "viewer"])
async def test_the_start_and_the_eligibility_port_read_the_owner_test_from_one_rule(
    monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    """Only a viewer is an Owner once the rule says so: neither side tests the role by name."""
    monkeypatch.setattr(scopes, "_holds_owner_role", lambda roles: "viewer" in roles)
    starts = await _the_start_lets_through("active", (role,))
    assert starts == await _the_port_keeps("active", [role]) == (role != "viewer")
