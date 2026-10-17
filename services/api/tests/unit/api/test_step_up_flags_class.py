"""#3083 (AD-F01): `flags`, the step-up class of a feature-flag write, is a grace class.

The contract lists `flags` in the `authStepUp` enum and `setFeatureFlag` says "every other
write needs `flags` (5-minute grace)". On `main` the service refused the class, so the flag
write had no class to demand: a step-up for it was `400`, a gate for it `500`.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any, cast

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.step_up import require_elevation_for
from candleviewer.auth import step_up as step_up_service
from candleviewer.auth.errors import StepUpRequired
from candleviewer.auth.step_up import GRACE_WINDOW, StepUpService
from tests.unit.auth.test_step_up import PASSWORD, _code, _setup


def _description(path: str, method: str) -> str:
    paths = cast(dict[str, Any], load_openapi_spec())["paths"]
    return " ".join(str(paths[path][method]["description"]).split())


def test_grace_placement_follows_the_contract_text() -> None:
    """`authStepUp` names the no-grace classes; `flags` is not among them."""
    named = re.search(
        r"((?:`\w+`(?:, | and )?)+) are no-grace", _description("/auth/step-up", "post")
    )
    assert named is not None
    assert set(re.findall(r"`(\w+)`", named[1])) == step_up_service.NO_GRACE_ACTION_CLASSES
    flag_write = _description("/admin/feature-flags/{flagKey}", "put")
    assert "every other write needs `flags` (5-minute grace)" in flag_write
    assert "flags" in step_up_service.ACTION_CLASSES - step_up_service.NO_GRACE_ACTION_CLASSES


async def test_flags_step_up_opens_a_five_minute_grace_window() -> None:
    svc, clock, seed, user, _ = await _setup()
    with pytest.raises(StepUpRequired):  # a challenge to answer, not an unknown class
        await svc.require_elevation("s1", "flags")
    grant = await svc.step_up(str(user), "s1", "flags", _code(seed, clock), PASSWORD)
    assert not grant.single_use
    assert grant.elevated_until == clock.now + GRACE_WINDOW
    clock.now += GRACE_WINDOW - timedelta(seconds=1)
    await svc.require_elevation("s1", "flags")
    clock.now += timedelta(seconds=1)
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s1", "flags")


class _Auth:
    """The part of `_AuthLike` that `require_elevation_for` reads."""

    def __init__(self, step_up: StepUpService) -> None:
        self.step_up = step_up
        self.step_up_is_active = True
        self.sessions_is_active = True
        self.sessions: object = None


async def test_a_flags_gate_issues_a_challenge_not_a_server_error() -> None:
    svc, *_ = await _setup()
    denied = await require_elevation_for(_Auth(svc), "s1", "flags")
    assert denied is not None and denied.status_code == 403
    body = json.loads(bytes(denied.body))
    assert (body["code"], body["action_class"]) == ("step_up_required", "flags")
