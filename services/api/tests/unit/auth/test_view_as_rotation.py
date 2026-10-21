"""#3085 S3 (SR-013): a refresh carries the session's view-as context to its successor as the
claim's RETURNING row holds it, unchanged and whatever its phase, never as the presented row was
read before the claim. The rotated row keeps its copy, and no other session changes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import SessionService
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
)

Write = Callable[[FakeSessionRepository, str], Awaitable[Any]]


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


@pytest.mark.parametrize(
    "state",
    [LIVE, PAST, ENDED, RECORDED, CLEARED, DONE],
    ids=["live", "held-by-expiry", "held-by-end", "held-recorded", "cleared-pending", "cleared"],
)
async def test_refresh_carries_context_unchanged(state: ViewAsState) -> None:
    """Nothing extends `expires_at`; a held context stays held across the refresh, a cleared one
    stays cleared with its pending end. The rotated row keeps its copy."""
    repo = FakeSessionRepository()
    await _session(repo, "viewer", state)
    rotated, successor = await _refresh(repo, "viewer")
    assert successor.view_as == rotated.view_as == state
    assert (rotated.revoked_reason, successor.revoked_at) == ("rotated", None)
    assert successor.view_as.phase(now=T0) is state.phase(now=T0)


class _WriteBeforeClaim(FakeSessionRepository):
    """`write` lands on the row after the refresh read it and before its claim."""

    def __init__(self, write: Write) -> None:
        super().__init__()
        self._write = write

    async def revoke(self, session_id: str, *, reason: str, now: Any) -> SessionRecord | None:
        if reason == "rotated":
            assert await self._write(self, session_id) is not None
        return await super().revoke(session_id, reason=reason, now=now)


_SWEEPER = ViewAsEndReason.SESSION_ENDED
#: case -> (the context the refresh read, the write before its claim, the context claimed)
_BETWEEN: dict[str, tuple[ViewAsState, Write, ViewAsState]] = {
    "an-end": (
        LIVE,
        lambda r, s: r.end_view_as(s, LIVE.context_id, ended_at=T0, reason=_SWEEPER),
        ended(LIVE, 0, _SWEEPER),
    ),
    "a-start": (DONE, lambda r, s: r.start_view_as(s, FRESH, now=T0), FRESH),
}


@pytest.mark.parametrize(("presented", "write", "claimed"), _BETWEEN.values(), ids=list(_BETWEEN))
async def test_carry_reads_claim_not_presented(
    presented: ViewAsState, write: Write, claimed: ViewAsState
) -> None:
    """A write between the read and the claim is carried, never undone: an ended context is not
    revived, a new one is not swapped back for the old."""
    repo = _WriteBeforeClaim(write)
    await _session(repo, "viewer", presented)
    rotated, successor = await _refresh(repo, "viewer")
    assert successor.view_as == rotated.view_as == claimed != presented


async def test_viewer_other_sessions_unaffected() -> None:
    """Only the refreshed row moves: the viewer's other session and the target's stay as they
    were, and refreshing the other session carries no context to its successor."""
    repo = FakeSessionRepository()
    await _session(repo, "viewer", LIVE)
    other = await _session(repo, "other", None)
    target = record("target", Row()).model_copy(update={"user_id": TARGET, "last_seen_at": T0})
    assert await repo.create_session(target) is not None
    untouched = {sid: repo.sessions[sid] for sid in (other, str(target.id))}
    _, successor = await _refresh(repo, "viewer")
    assert {sid: repo.sessions[sid] for sid in untouched} == untouched
    _, other_successor = await _refresh(repo, "other")
    assert other_successor.view_as is None
    assert repo.sessions[str(successor.id)].view_as == LIVE
