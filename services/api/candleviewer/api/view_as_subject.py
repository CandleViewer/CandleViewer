"""Whose scope a request of a view-as session answers in (#3085 S8; plan 1.3, Q2).

The view-as guard (`api/view_as_guard.py`) stamps every request it passes for a session holding
a context. A resolver that turns the bearer into a principal asks `view_as_subject` whose
principal to build: the target on a live read, the viewer for the rest. A record and a budget
then name the viewer as the actor. This module imports no router, so every resolver can use it.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from fastapi import Request

from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import ViewAsRequestContext

#: Where a passing request carries its context (plan 1.3), beside the `bound_view_as` contextvar.
STATE_KEY: Final = "cv.view_as"


class ViewAsUnstamped(Exception):
    """A session holds a view-as context its request carries no stamp for (#3085 S8): the guard
    read the row before the context started, or another context replaced it since. The app
    answers `503 store_unavailable` (`view_as_unstamped_handler`), never the session's own scope
    in its place."""


def view_as_stamp(request: Request) -> ViewAsRequestContext | None:
    """The context the guard stamped on `request`, or `None`."""
    stamp = request.scope.get("state", {}).get(STATE_KEY)
    return stamp if isinstance(stamp, ViewAsRequestContext) else None


def view_as_subject(request: Request, record: SessionRecord) -> UUID:
    """The user a request of `record`'s session answers as (#3085 S8, Q2): the session's own user
    while it holds no context (none, or a cleared one); otherwise the subject the guard stamped
    for that very context, the target on a live read and the viewer for the rest. A context with
    no matching stamp raises `ViewAsUnstamped`."""
    state = record.view_as
    if state is None or state.cleared_at is not None:
        return record.user_id
    stamp = view_as_stamp(request)
    if (
        stamp is None
        or stamp.context_id != state.context_id
        or stamp.viewer_session_id != record.id
    ):
        raise ViewAsUnstamped
    return stamp.subject_user_id
