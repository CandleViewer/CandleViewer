"""#2304: the `POST /auth/step-up` `200` echoes the `challenge_id` the grant consumed (defence
in depth), and never one it did not consume. Omitted when no challenge was consumed."""

from __future__ import annotations

import uuid

import pytest

from tests.unit.api.test_step_up_challenge_router import _RELEASE, _world


async def test_200_echoes_the_challenge_id_the_request_named() -> None:
    w = await _world()
    denied = w.client.post(f"/users/{uuid.uuid4()}/invite", headers=w.h())
    challenge_id = denied.json()["challenge_id"]
    ok = w.step_up(challenge_id=challenge_id)
    assert ok.status_code == 200
    assert ok.json()["challenge_id"] == challenge_id


async def test_200_echoes_the_matched_challenge_for_a_no_grace_class() -> None:
    w = await _world()
    challenge_id = w.send(_RELEASE).json()["challenge_id"]
    ok = w.step_up(challenge_id=challenge_id)
    assert ok.status_code == 200 and ok.json()["single_use"] is True
    assert ok.json()["challenge_id"] == challenge_id
    (granted,) = w.of("auth.step_up_granted")
    assert granted["object_id"] == challenge_id  # the audited id is the echoed one


async def test_200_echoes_the_live_challenge_when_a_grace_step_up_sends_none() -> None:
    w = await _world()
    challenge_id = w.client.post(f"/users/{uuid.uuid4()}/invite", headers=w.h()).json()[
        "challenge_id"
    ]
    ok = w.step_up()  # the server matched the session's live challenge
    assert ok.status_code == 200 and ok.json()["challenge_id"] == challenge_id


@pytest.mark.parametrize("action_class", ["keys", "users"])
async def test_200_omits_challenge_id_for_a_grace_class_without_a_challenge(
    action_class: str,
) -> None:
    w = await _world()
    ok = w.step_up(action_class=action_class)
    assert ok.status_code == 200
    assert "challenge_id" not in ok.json()


async def test_200_never_echoes_a_challenge_the_grant_did_not_consume() -> None:
    """A stale id is a 400 with no grant, so no id reaches a `200` body."""
    w = await _world()
    w.send(_RELEASE)
    stale = w.step_up(challenge_id=str(uuid.uuid4()))
    assert stale.status_code == 400 and "challenge_id" not in stale.json()
