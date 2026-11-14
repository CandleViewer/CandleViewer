"""#3085 S3 (SR-013): a refresh carries the session's view-as context to its successor as the
claim's RETURNING row holds it, unchanged and whatever its phase, never as the presented row was
read before the claim. A step-up's rotation (`rotate`, #2101) carries it the same way, through the
same carrier (`_mint_successor`), and neither widens it: the successor holds the claim's context,
its target and expiry, and the claim's absolute expiry. The rotated row keeps its copy, and no
other session changes."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import carried_grants
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsState

from .session_fakes import FakeSessionRepository
from .view_as_store_scenarios import (
    CLEARED,
    DONE,
    ENDED,
    FRESH,
    LIVE,
    PAST,
    RECORDED,
    T0,
    TARGET,
    Row,
    ended,
    record,
    session_id,
    with_,
)

Write = Callable[[FakeSessionRepository, str], Awaitable[Any]]
#: A rotation of the session of a raw refresh token: the rotated row and its successor, as stored.
Rotation = Callable[[FakeSessionRepository, str], Awaitable[tuple[SessionRecord, SessionRecord]]]


async def _session(repo: FakeSessionRepository, token: str, state: ViewAsState | None) -> str:
    """A viewer session active at `T0` holding `state`; its raw refresh token is `token`."""
    row = record(token, Row(state)).model_copy(update={"last_seen_at": T0})
    assert await repo.create_session(row) is not None
    return str(row.id)


async def _refresh(repo: FakeSessionRepository, token: str) -> tuple[SessionRecord, SessionRecord]:
    """Refresh the session of `token`: the rotated row and its successor, as stored."""
    outcome = await SessionService(repo, Hasher(pepper="p"), clock=lambda: T0).refresh(token)
    rotated = repo.sessions[str(outcome.previous_session_id)]
    return rotated, repo.sessions[str(outcome.minted.session_id)]


async def _rotate(repo: FakeSessionRepository, token: str) -> tuple[SessionRecord, SessionRecord]:
    """Rotate the session of `token` as a step-up does, keeping the grants a step-up keeps (none
    here): the rotated row and its successor, as stored."""
    service = SessionService(repo, Hasher(pepper="p"), clock=lambda: T0)
    outcome = await service.rotate(
        str(session_id(token)), successor_id=uuid.uuid4(), carry_grants=carried_grants
    )
    rotated = repo.sessions[str(outcome.previous_session_id)]
    return rotated, repo.sessions[str(outcome.minted.session_id)]


_ROTATIONS: dict[str, Rotation] = {"refresh": _refresh, "rotate": _rotate}
_each_rotation = pytest.mark.parametrize("rotation", _ROTATIONS.values(), ids=list(_ROTATIONS))


@_each_rotation
@pytest.mark.parametrize(
    "state",
    [LIVE, PAST, ENDED, RECORDED, CLEARED, DONE],
    ids=["live", "held-by-expiry", "held-by-end", "held-recorded", "cleared-pending", "cleared"],
)
async def test_successor_carries_context_unchanged(rotation: Rotation, state: ViewAsState) -> None:
    """Nothing extends `expires_at`; a held context stays held across the rotation, a cleared one
    stays cleared with its pending end. The rotated row keeps its copy, and the successor keeps
    the claim's absolute expiry."""
    repo = FakeSessionRepository()
    await _session(repo, "viewer", state)
    rotated, successor = await rotation(repo, "viewer")
    assert successor.view_as == rotated.view_as == state
    assert (rotated.revoked_reason, successor.revoked_at) == ("rotated", None)
    assert successor.view_as.phase(now=T0) is state.phase(now=T0)
    assert successor.expires_at == rotated.expires_at


class _WriteBeforeClaim(FakeSessionRepository):
    """`write` lands on the row after the caller read it and before the rotation's claim."""

    def __init__(self, write: Write) -> None:
        super().__init__()
        self._write = write

    async def revoke(self, session_id: str, *, reason: str, now: Any) -> SessionRecord | None:
        if reason == "rotated":
            assert await self._write(self, session_id) is not None
        return await super().revoke(session_id, reason=reason, now=now)


_SWEEPER, _VIEWER = ViewAsEndReason.SESSION_ENDED, ViewAsEndReason.ENDED
#: case -> (the context the caller read, the write before the claim, the context claimed)
_BETWEEN: dict[str, tuple[ViewAsState, Write, ViewAsState]] = {
    "an-end": (
        LIVE,
        lambda r, s: r.end_view_as(s, LIVE.context_id, ended_at=T0, reason=_SWEEPER),
        ended(LIVE, 0, _SWEEPER),
    ),
    "a-leave": (
        LIVE,
        lambda r, s: r.leave_view_as(s, LIVE.context_id, ended_at=T0, reason=_VIEWER, now=T0),
        with_(ended(LIVE, 0, _VIEWER), cleared_at=T0),
    ),
    "a-clear": (
        ENDED,
        lambda r, s: r.clear_view_as(s, LIVE.context_id, now=T0),
        with_(ENDED, cleared_at=T0),
    ),
    "a-start": (DONE, lambda r, s: r.start_view_as(s, FRESH, now=T0), FRESH),
}


@_each_rotation
@pytest.mark.parametrize(("presented", "write", "claimed"), _BETWEEN.values(), ids=list(_BETWEEN))
async def test_carry_reads_claim_not_presented(
    rotation: Rotation, presented: ViewAsState, write: Write, claimed: ViewAsState
) -> None:
    """A write between the read and the claim is carried, never undone: an ended or cleared
    context is not revived, a new one is not swapped back for the old."""
    repo = _WriteBeforeClaim(write)
    await _session(repo, "viewer", presented)
    rotated, successor = await rotation(repo, "viewer")
    assert successor.view_as == rotated.view_as == claimed != presented


@_each_rotation
async def test_viewer_other_sessions_unaffected(rotation: Rotation) -> None:
    """Only the rotated row moves: the viewer's other session and the target's stay as they
    were, and rotating the other session carries no context to its successor."""
    repo = FakeSessionRepository()
    await _session(repo, "viewer", LIVE)
    other = await _session(repo, "other", None)
    target = record("target", Row()).model_copy(update={"user_id": TARGET, "last_seen_at": T0})
    assert await repo.create_session(target) is not None
    untouched = {sid: repo.sessions[sid] for sid in (other, str(target.id))}
    _, successor = await rotation(repo, "viewer")
    assert {sid: repo.sessions[sid] for sid in untouched} == untouched
    _, other_successor = await rotation(repo, "other")
    assert other_successor.view_as is None
    assert repo.sessions[str(successor.id)].view_as == LIVE
