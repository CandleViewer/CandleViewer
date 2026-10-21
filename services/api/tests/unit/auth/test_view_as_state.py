"""#3085: the view-as state, its phase and its end, and the request context (22-api-openapi.yaml,
"View-as session"). The models refuse what the `sessions` CHECKs of the #3085 migration refuse."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from candleviewer.auth import view_as
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsPhase, ViewAsState

from .test_step_up import _T0, _session

_US, _TTL = timedelta(microseconds=1), view_as.VIEW_AS_TTL
_EXPIRY, _END, _EARLY = _T0 + _TTL, _T0 + timedelta(minutes=10), _T0 - timedelta(hours=1)
_LATE, _NAIVE = _EXPIRY + _US, _END.replace(tzinfo=None)
_CONTEXT, _TARGET, _VIEWER = UUID(int=1), UUID(int=2), UUID(int=3)
_ENDED: dict[str, Any] = {"ended_at": _END, "end_reason": ViewAsEndReason.ENDED}
_EXPIRED, (_NONE, _LIVE, _HELD) = ViewAsEndReason.EXPIRED, tuple(ViewAsPhase)
_ASKED = [reason for reason in ViewAsEndReason if reason is not _EXPIRED]


def _state(**fields: Any) -> ViewAsState:
    """The context started at `_T0`, with `fields` changed: `model_copy` validates as a row."""
    return ViewAsState.start(_CONTEXT, _TARGET, now=_T0).model_copy(update=fields)


def _context(**fields: Any) -> view_as.ViewAsRequestContext:
    ids = {"viewer_user_id": _VIEWER, "target_user_id": _TARGET, "subject_user_id": _TARGET}
    rest = {"viewer_session_id": UUID(int=4), "context_id": _CONTEXT, "viewer_label": "owner"}
    return view_as.ViewAsRequestContext(**{**ids, **rest, "phase": "live", **fields})


#: case id -> (call, keyword arguments, message fragment): each rule refused by one row at least.
_REFUSED: dict[str, tuple[Callable[..., object], dict[str, Any], str]] = {
    "expiry-not-start-plus-30m": (_state, {"expires_at": _LATE}, "started_at plus"),
    "end-without-reason": (_state, {"ended_at": _END}, "set together"),
    "reason-without-end": (_state, {"end_reason": "ended"}, "set together"),
    "recorded-without-end": (_state, {"end_recorded_at": _END}, "without ended_at"),
    "cleared-without-end": (_state, {"cleared_at": _END}, "without ended_at"),
    "end-after-expiry": (_state, {"ended_at": _LATE, "end_reason": "expired"}, "not be after"),
    "expired-before-expiry": (_state, {"ended_at": _END, "end_reason": "expired"}, "exactly when"),
    "ended-at-expiry": (_state, {"ended_at": _EXPIRY, "end_reason": "ended"}, "exactly when"),
    "naive-start": (_state, {"started_at": _NAIVE}, "timezone-aware"),
    "naive-clear": (_state, {**_ENDED, "cleared_at": _NAIVE}, "timezone-aware"),
    "naive-phase-now": (_state().phase, {"now": _NAIVE}, "timezone-aware"),
    "unknown-reason": (_state, {**_ENDED, "end_reason": "logout"}, "Input should be"),
    "unknown-field": (_state, {"reason": "why"}, "Extra inputs"),
    "second-end": (_state(**_ENDED).end_at, {"now": _END, "reason": "ended"}, "exactly once"),
    "expired-asked-early": (_state().end_at, {"now": _END, "reason": _EXPIRED}, "derived"),
    "viewer-is-target": (_context, {"target_user_id": _VIEWER}, "not be the target"),
    "subject-neither": (_context, {"subject_user_id": UUID(int=9)}, "viewer or the target"),
    "held-as-target": (_context, {"phase": "held"}, "answers as the viewer"),
    "no-actor-label": (_context, {"viewer_label": ""}, "at least 1 character"),
    "own-user": (SessionRecord, {**dict(_session(_TARGET)), "view_as": _state()}, "own user"),
}


@pytest.mark.parametrize(("call", "kwargs", "match"), list(_REFUSED.values()), ids=list(_REFUSED))
def test_models_refuse_what_the_row_and_the_contract_refuse(
    call: Callable[..., object], kwargs: dict[str, Any], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        call(**kwargs)


def test_phase_live_at_29m59s_held_at_30m00s() -> None:
    assert _state().phase(now=_T0 + timedelta(minutes=29, seconds=59)) is _LIVE
    assert _state().phase(now=_T0 + timedelta(minutes=30)) is _HELD


def test_expires_at_is_started_plus_30m() -> None:
    plus_five = (_T0 + timedelta(hours=5)).replace(tzinfo=timezone(timedelta(hours=5)))
    state = ViewAsState.start(_CONTEXT, _TARGET, now=plus_five)  # the instant `_T0`
    assert (state.started_at, state.expires_at) == (_T0, _T0 + timedelta(minutes=30))
    assert state.started_at.tzinfo is state.expires_at.tzinfo is UTC


def test_end_reasons_are_the_five_of_end_view_as() -> None:
    contract = "ended expired viewer_ineligible target_ineligible session_ended"  # `endViewAs`
    assert sorted(ViewAsEndReason) == sorted(contract.split())


#: case id -> (`now`, the reason asked, the `(ended_at, end_reason)` the write records)
_ENDS: dict[str, tuple[datetime, ViewAsEndReason, tuple[datetime, ViewAsEndReason]]] = {
    **{f"before-expiry-{r}": (_EXPIRY - _US, r, (_EXPIRY - _US, r)) for r in _ASKED},
    **{f"at-expiry-{r}": (_EXPIRY, r, (_EXPIRY, _EXPIRED)) for r in ViewAsEndReason},
    **{f"after-expiry-{r}": (_LATE, r, (_EXPIRY, _EXPIRED)) for r in ViewAsEndReason},
    "clock-stepped-back": (_EARLY, ViewAsEndReason.ENDED, (_T0, ViewAsEndReason.ENDED)),
}


@pytest.mark.parametrize(("now", "asked", "recorded"), list(_ENDS.values()), ids=list(_ENDS))
def test_end_at_gives_the_end_a_write_records(
    now: datetime, asked: ViewAsEndReason, recorded: tuple[datetime, ViewAsEndReason]
) -> None:
    assert _state().end_at(now=now, reason=asked) == recorded


_BOUND: dict[str, Any] = dict(context_id=_CONTEXT, target_user_id=_TARGET, expires_at=_EXPIRY)
#: case id -> (the context, if any; its phase and the binding it gives at `_END`)
_AT_END: dict[str, tuple[ViewAsState | None, ViewAsPhase, view_as.ViewAsBinding | None]] = {
    "live": (_state(), _LIVE, view_as.ViewAsBinding(**_BOUND, phase=ViewAsPhase.LIVE)),
    "held": (_state(**_ENDED), _HELD, view_as.ViewAsBinding(**_BOUND, phase=ViewAsPhase.HELD)),
    "cleared-at-any-time": (_state(**_ENDED, cleared_at=_EARLY), _NONE, None),
    "a-pre-3085-record-holds-none": (_session(_VIEWER).view_as, _NONE, None),
}


@pytest.mark.parametrize(("state", "phase", "binding"), list(_AT_END.values()), ids=list(_AT_END))
def test_phase_and_the_binding_it_gives_follow_the_end_and_the_clear(
    state: ViewAsState | None, phase: ViewAsPhase, binding: view_as.ViewAsBinding | None
) -> None:
    bound = state and state.binding(now=_END)  # a session without a context binds nothing
    assert (view_as.view_as_phase(state, now=_END), bound) == (phase, binding)


def test_request_context_views_as_the_target_only_when_it_is_the_subject() -> None:
    assert _context().is_viewing_as_target
    assert not _context(subject_user_id=_VIEWER, phase="held").is_viewing_as_target


def test_request_context_repr_leaves_out_the_viewer_session_id() -> None:
    assert "viewer_session_id" not in repr(_context())


async def test_bound_view_as_resets_on_every_exit_and_is_local_to_each_task() -> None:
    contexts = outer, inner = _context(), _context(subject_user_id=_VIEWER, phase="held")
    with view_as.bound_view_as(outer):
        with pytest.raises(RuntimeError), view_as.bound_view_as(inner):
            assert view_as.current_view_as() is inner
            raise RuntimeError("the handler failed")
        assert view_as.current_view_as() is outer  # the inner token is reset, not the value cleared
    bound = (asyncio.Event(), asyncio.Event())

    async def handle(mine: int) -> view_as.ViewAsRequestContext | None:
        with view_as.bound_view_as(contexts[mine]):
            bound[mine].set()
            await bound[1 - mine].wait()  # both tasks are inside their blocks now
            return view_as.current_view_as()

    assert list(await asyncio.gather(handle(0), handle(1))) == [outer, inner]
    assert view_as.current_view_as() is None


@example(start_us=0, t1_us=_TTL // _US - 1, gap_us=1)  # live 1 us before `expires_at`, held at it
@given(
    start_us=st.integers(min_value=-(10**12), max_value=10**12),
    t1_us=st.integers(min_value=-(_TTL // _US), max_value=2 * (_TTL // _US)),
    gap_us=st.integers(min_value=0, max_value=2 * (_TTL // _US)),
)
def test_phase_never_returns_from_held_to_live_and_is_live_exactly_before_expiry(
    start_us: int, t1_us: int, gap_us: int
) -> None:
    state = ViewAsState.start(_CONTEXT, _TARGET, now=_T0 + start_us * _US)  # not ended
    t1, t2 = state.started_at + t1_us * _US, state.started_at + (t1_us + gap_us) * _US
    first, second = state.phase(now=t1), state.phase(now=t2)
    assert (first, second) != (_HELD, _LIVE)
    assert (first is _LIVE) is (t1 < state.expires_at)
    assert (second is _LIVE) is (t2 < state.expires_at)
