"""#3085 S2b: one scenario table for `ViewAsSessionStore`, played against the in-memory fake
(`test_view_as_store_parity.py`, a unit test) and against Postgres
(`tests/integration/storage/test_sessions_view_as_store_pg.py`), so the two never drift. A scenario
inserts its rows and acts through the store's own methods (`SessionRepository` and
`ViewAsSessionStore`), never a fake's internals; `play` returns plain data and asserts nothing.
The one state no store method makes, a `revoked_reason` with no `revoked_at`, is written by the
harness's own `Stamp`. Not collected itself (no `test_` prefix)."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsNotice, ViewAsState

#: The viewer, whose rows these are, and the two users a context names (the Postgres half inserts
#: these three `users` rows).
VIEWER, TARGET, OTHER = UUID(int=0xA1), UUID(int=0xB2), UUID(int=0xB3)
T0 = datetime(2026, 10, 20, 12, tzinfo=UTC)
GRACE = timedelta(minutes=1)  # every due read's `rotated_grace`
#: A harness's raw write of a row's `revoked_reason` alone (session id, reason): no store method
#: leaves a row revoked with no time, but a raw write could, and the due read must treat it as live.
Stamp = Callable[[str, str], Awaitable[None]]
_BY_SWEEPER, _BY_VIEWER = ViewAsEndReason.SESSION_ENDED, ViewAsEndReason.ENDED


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def with_(state: ViewAsState, **changes: Any) -> ViewAsState:
    return state.model_copy(update=changes)


def ended(state: ViewAsState, minutes: float, reason: ViewAsEndReason = _BY_VIEWER) -> ViewAsState:
    return with_(state, ended_at=at(minutes), end_reason=reason)


LIVE = ViewAsState.start(UUID(int=1), TARGET, now=at(-10))  # expires at +20
PAST = ViewAsState.start(UUID(int=2), TARGET, now=at(-40))  # expired at -10, never ended
LATE = ViewAsState.start(UUID(int=3), OTHER, now=at(-5))  # expires at +25, another target
ENDED = ended(LIVE, -5)  # its record still owed
RECORDED = with_(ENDED, end_recorded_at=at(-4))
CLEARED = with_(ENDED, cleared_at=at(-3))  # cleared, its record still owed
DONE = with_(RECORDED, cleared_at=at(-3))  # a new start may replace it
PAST_ENDED = ended(PAST, -10, ViewAsEndReason.EXPIRED)
FRESH = ViewAsState.start(UUID(int=9), TARGET, now=T0)  # what a start puts on a row
SELF = ViewAsState.start(UUID(int=8), VIEWER, now=T0)  # names the viewer's own user: refused


@dataclass(frozen=True)
class Row:
    """A viewer's row: the context it is inserted with, its revocation (reason, minute) if any
    (a minute of `None`: the reason alone, written by the harness's `Stamp`), and its absolute
    expiry (minutes from `T0`)."""

    view_as: ViewAsState | None = None
    revoked: tuple[str, float | None] | None = None
    expires: float = 600


@dataclass(frozen=True)
class Call:
    """`method` with `kwargs`, on the row labelled `row` (its first argument) if any. `unordered`:
    a list the contract does not order, compared as sorted labels."""

    method: str
    row: str | None = None
    kwargs: Mapping[str, Any] = field(default_factory=dict)
    unordered: bool = False


@dataclass(frozen=True)
class Scenario:
    """Rows, calls in order, and per call its outcome: `None` (refused), `(label, state)` (a write
    applied; `leave_view_as` adds whether it ended the context), the labels a list returns, or
    `"ValueError"` (a caller error)."""

    id: str
    rows: Mapping[str, Row]
    calls: tuple[Call, ...]
    expect: tuple[object, ...]


def start(state: ViewAsState = FRESH) -> Call:
    return Call("start_view_as", "a", {"state": state, "now": T0})


async def _written(_record: object) -> None:
    """A start's write-ahead hook that writes its record."""


def start_unit(state: ViewAsState = FRESH, *, to: UUID = TARGET) -> Call:
    """The start request's unit of work (#3085 S13a), its hooks writing their records; its notice
    addressed `to` the state's target unless a scenario says otherwise."""
    kwargs = {"state": state, "now": T0, "notice": ViewAsNotice(to, "m", None)}
    hooks = {"flush_pending_end": _written, "write_ahead": _written, "audit_timeout_s": 5.0}
    return Call("start_view_as_unit", "a", kwargs | hooks)


def end(reason: ViewAsEndReason = _BY_SWEEPER) -> Call:
    return Call(
        "end_view_as", "a", {"context_id": LIVE.context_id, "ended_at": T0, "reason": reason}
    )


def leave(state: ViewAsState = LIVE) -> Call:
    kwargs = {"context_id": state.context_id, "ended_at": T0, "reason": _BY_VIEWER, "now": T0}
    return Call("leave_view_as", "a", kwargs)


def clear(minutes: float = 0) -> Call:
    return Call("clear_view_as", "a", {"context_id": LIVE.context_id, "now": at(minutes)})


def mark(minutes: float = 0) -> Call:
    return Call("mark_view_as_recorded", "a", {"context_id": LIVE.context_id, "now": at(minutes)})


def due(limit: int = 9, minutes: float = 0, *, unordered: bool = False) -> Call:
    kwargs = {"now": at(minutes), "rotated_grace": GRACE, "limit": limit}
    return Call("list_view_as_due", None, kwargs, unordered)


def live(limit: int = 9) -> Call:
    return Call("list_live_view_as", None, {"limit": limit})


def by_target(target: UUID = TARGET) -> Call:
    return Call("list_live_view_as_by_target", None, {"target_user_id": target}, unordered=True)


def by_viewer(viewer: UUID = VIEWER) -> Call:
    return Call("list_live_view_as_by_viewer", None, {"viewer_user_id": viewer}, unordered=True)


def _one(sid: str, call: Call, expect: object, **rows: Row) -> Scenario:
    return Scenario(sid, rows, (call,), (expect,))


_LOGOUT, _OLD, _PAST_GRACE, _AT_GRACE, _IN_GRACE = (
    ("logout", -2.0),
    ("rotated", -30.0),
    ("rotated", -2.0),
    ("rotated", -1.0),
    ("rotated", -0.5),
)
_E0 = ended(LIVE, 0, _BY_VIEWER)
_END_A = ("a", ended(LIVE, 0, _BY_SWEEPER))  # the outcome of `end()` applying to row `a`
_LISTED = {"a": Row(LIVE), "p": Row(PAST), "l": Row(LATE), "e": Row(ENDED)}
_LISTED |= {"r": Row(LIVE, _LOGOUT), "n": Row()}
#: The insert writes the context a record carries, each state as it is (S3's carry).
_EVERY_STATE = {"none": None, "live": LIVE, "past": PAST, "ended": ENDED, "recorded": RECORDED}
_EVERY_STATE |= {"cleared": CLEARED, "done": DONE, "past-ended": PAST_ENDED}

SCENARIOS: tuple[Scenario, ...] = (
    Scenario("insert-carries-every-state", {k: Row(v) for k, v in _EVERY_STATE.items()}, (), ()),
    # start: no context, or a cleared one whose end is recorded; never on a revoked or
    # absolute-expired row; a fresh state only.
    _one("start-on-none", start(), ("a", FRESH), a=Row()),
    _one("start-on-cleared-and-recorded", start(), ("a", FRESH), a=Row(DONE)),
    _one("start-on-live", start(), None, a=Row(LIVE)),
    _one("start-on-ended", start(), None, a=Row(ENDED)),
    _one("start-on-recorded", start(), None, a=Row(RECORDED)),
    _one("start-on-cleared-pending", start(), None, a=Row(CLEARED)),
    _one("start-on-revoked", start(), None, a=Row(revoked=_LOGOUT)),
    _one("start-on-absolute-expired", start(), None, a=Row(expires=0)),
    _one("start-an-ended-state", start(ended(FRESH, 1)), "ValueError", a=Row()),
    # a state naming the row's own user is refused where the write would apply (only the row knows
    # its user); a row that refuses a start answers None first
    _one("start-a-self-targeting-state", start(SELF), "ValueError", a=Row()),
    _one("start-a-self-target-on-a-revoked-row", start(SELF), None, a=Row(revoked=_LOGOUT)),
    # #3085 S13a: the start's unit. As the start, but a cleared context whose record is owed gets
    # it late and is replaced; a context it cannot replace answers held, which reads refused here.
    _one("unit-on-none", start_unit(), ("a", FRESH), a=Row()),
    _one("unit-on-cleared-and-recorded", start_unit(), ("a", FRESH), a=Row(DONE)),
    _one("unit-on-cleared-pending", start_unit(), ("a", FRESH), a=Row(CLEARED)),
    _one("unit-on-live", start_unit(), None, a=Row(LIVE)),
    _one("unit-on-ended", start_unit(), None, a=Row(ENDED)),
    _one("unit-on-revoked", start_unit(), None, a=Row(revoked=_LOGOUT)),
    _one("unit-on-absolute-expired", start_unit(), None, a=Row(expires=0)),
    _one("unit-an-ended-state", start_unit(ended(FRESH, 1)), "ValueError", a=Row()),
    _one("unit-a-self-targeting-state", start_unit(SELF), "ValueError", a=Row()),
    _one("unit-a-notice-to-another-user", start_unit(to=OTHER), "ValueError", a=Row()),
    # end: that context, not ended; a revoked row too (the sweeper ends `session_ended` there)
    # unless another, unrevoked row holds it: its successor carries it on
    _one("end-live", end(), ("a", ended(LIVE, 0, _BY_SWEEPER)), a=Row(LIVE)),
    _one("end-on-revoked", end(), ("a", ended(LIVE, 0, _BY_SWEEPER)), a=Row(LIVE, _LOGOUT)),
    _one("end-ended", end(), None, a=Row(ENDED)),
    _one("end-other-context", end(), None, a=Row(PAST)),
    _one("end-none", end(), None, a=Row()),
    _one("end-on-an-orphaned-rotated-copy", end(), _END_A, a=Row(LIVE, _OLD)),
    _one(
        "end-on-a-rotated-copy-its-successor-carries", end(), None, a=Row(LIVE, _OLD), b=Row(LIVE)
    ),
    _one(
        "end-on-a-rotated-copy-whose-other-holder-is-revoked",
        end(),
        _END_A,
        a=Row(LIVE, _OLD),
        b=Row(LIVE, _LOGOUT),
    ),
    # leave: that context, not cleared, unrevoked (a rotated predecessor's copy is not the
    # context its successor carries on); ends it unless ended, and clears it, in one write
    _one("leave-live", leave(), ("a", with_(_E0, cleared_at=T0), True), a=Row(LIVE)),
    _one("leave-ended", leave(), ("a", with_(ENDED, cleared_at=T0), False), a=Row(ENDED)),
    _one(
        "leave-keeps-the-end-it-finds-even-an-expiry",
        leave(PAST),  # asked `ended` at T0; the end found is `expired` at its expiry, which stays
        ("a", with_(PAST_ENDED, cleared_at=T0), False),
        a=Row(PAST_ENDED),
    ),
    _one("leave-cleared", leave(), None, a=Row(CLEARED)),
    _one("leave-other-context", leave(), None, a=Row(PAST)),
    _one("leave-on-revoked", leave(), None, a=Row(LIVE, _IN_GRACE)),
    # clear: that context, ended, not cleared; the end and its pending record stay
    _one("clear-ended", clear(), ("a", with_(ENDED, cleared_at=T0)), a=Row(ENDED)),
    _one("clear-live", clear(), None, a=Row(LIVE)),
    _one("clear-cleared", clear(), None, a=Row(CLEARED)),
    _one("clear-other-context", clear(), None, a=Row(PAST_ENDED)),
    # mark: that context, ended, not recorded
    _one("mark-ended", mark(), ("a", with_(ENDED, end_recorded_at=T0)), a=Row(ENDED)),
    _one("mark-cleared", mark(), ("a", with_(CLEARED, end_recorded_at=T0)), a=Row(CLEARED)),
    _one("mark-live", mark(), None, a=Row(LIVE)),
    _one("mark-recorded", mark(), None, a=Row(RECORDED)),
    _one("mark-other-context", mark(), None, a=Row(PAST_ENDED)),
    Scenario(
        "clear-keeps-a-pending-end",
        {"a": Row(LIVE)},
        (end(_BY_VIEWER), clear(1), due(minutes=1), mark(2), due(minutes=2)),
        (
            ("a", _E0),
            ("a", with_(_E0, cleared_at=at(1))),
            ("a",),
            ("a", with_(_E0, cleared_at=at(1), end_recorded_at=at(2))),
            (),
        ),
    ),
    # due: unrecorded, and ended, past its expiry, or on a revoked or absolute-expired row
    _one("due-ended", due(), ("a",), a=Row(ENDED)),
    _one("due-past-expiry", due(), ("a",), a=Row(PAST)),
    _one("due-at-view-expiry", due(minutes=20), ("a",), a=Row(LIVE)),  # LIVE expires at +20
    _one("due-on-revoked", due(), ("a",), a=Row(LIVE, _LOGOUT)),
    _one("due-on-absolute-expired", due(), ("a",), a=Row(LIVE, expires=0)),
    _one("due-cleared-pending", due(), ("a",), a=Row(CLEARED)),
    _one("not-due-recorded", due(), (), a=Row(RECORDED), b=Row(DONE)),
    _one("not-due-in-time", due(), (), a=Row(LIVE), b=Row()),
    _one(
        "due-earliest-expiry-first",
        due(),
        ("b", "a", "c"),
        a=Row(ENDED),
        b=Row(PAST),
        c=Row(ended(LATE, -1)),
    ),
    _one(
        "due-honours-limit", due(2), ("b", "a"), a=Row(ENDED), b=Row(PAST), c=Row(ended(LATE, -1))
    ),
    # a rotated row: due only once every row holding its context rotated at least GRACE ago
    _one("rotated-carried-by-a-live-row", due(), (), a=Row(LIVE, _OLD), b=Row(LIVE)),
    _one("rotated-orphan-past-grace", due(), ("a",), a=Row(LIVE, _PAST_GRACE)),
    _one("rotated-orphan-at-grace", due(), ("a",), a=Row(LIVE, _AT_GRACE)),
    _one("rotated-orphan-in-grace", due(), (), a=Row(LIVE, _IN_GRACE)),
    _one("rotated-chain-last-in-grace", due(), (), a=Row(LIVE, _OLD), b=Row(LIVE, _IN_GRACE)),
    _one(
        "rotated-chain-past-grace",
        due(unordered=True),  # one context, one expiry: no order between them
        ("a", "b"),
        a=Row(LIVE, _OLD),
        b=Row(LIVE, _PAST_GRACE),
    ),
    _one(
        "rotated-carried-by-a-logged-out-row",
        due(),
        ("b",),
        a=Row(LIVE, _OLD),
        b=Row(LIVE, _LOGOUT),
    ),
    _one("rotated-carried-by-an-ended-copy", due(), ("b",), a=Row(LIVE, _OLD), b=Row(ENDED)),
    # no store method leaves a row revoked `rotated` with no time, but a raw write (a `Stamp`) could
    # and such a row is live: it carries
    _one(
        "rotated-carried-by-a-rotated-row-with-no-time",
        due(),
        (),
        a=Row(LIVE, _OLD),
        b=Row(LIVE, ("rotated", None)),
    ),
    # live: unrevoked, unended (lazily held included), earliest expiry first; by target: unordered
    Scenario(
        "live-earliest-expiry-first", _LISTED, (live(), live(2)), (("p", "a", "l"), ("p", "a"))
    ),
    Scenario("live-by-target", _LISTED, (by_target(), by_target(OTHER)), (("a", "p"), ("l",))),
    # by viewer: every unrevoked, unended context of the viewer's sessions, unordered
    Scenario("live-by-viewer", _LISTED, (by_viewer(), by_viewer(OTHER)), (("a", "l", "p"), ())),
)


def session_id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"cv-view-as-parity/{label}")


def record(label: str, row: Row) -> SessionRecord:
    return SessionRecord(
        id=session_id(label),
        user_id=VIEWER,
        refresh_token_hash=hashlib.sha256(label.encode()).hexdigest(),
        access_token_jti=None,
        issued_at=at(-60),
        last_seen_at=at(-60),
        expires_at=at(row.expires),
        revoked_at=None,
        revoked_reason=None,
        ip=None,
        user_agent=None,
        device_label=None,
        is_electron=False,
        mfa_satisfied_at=at(-60),
        view_as=row.view_as,
    )


async def play(
    store: Any, scenario: Scenario, stamp: Stamp | None = None
) -> tuple[tuple[object, ...], dict[str, Any]]:
    """Insert the rows, make the calls; each call's outcome, then every row's context. `stamp`
    writes a reason with no time, for a row that has one (the one state no store method makes)."""
    labels = {str(session_id(label)): label for label in scenario.rows}
    for label, row in scenario.rows.items():
        if await store.create_session(record(label, row)) is None:
            raise AssertionError(f"{scenario.id}: row {label} was not inserted")
        if row.revoked is not None:
            reason, minutes = row.revoked
            sid = str(session_id(label))
            if minutes is None:
                if stamp is None:
                    raise AssertionError(f"{scenario.id}: row {label} needs a Stamp")
                await stamp(sid, reason)
            elif await store.revoke(sid, reason=reason, now=at(minutes)) is None:
                raise AssertionError(f"{scenario.id}: row {label} was not revoked")
    outcomes = tuple([await _outcome(store, call, labels) for call in scenario.calls])
    final: dict[str, Any] = {}
    for label in scenario.rows:
        found = await store.find_by_id(str(session_id(label)))
        final[label] = "missing" if found is None else found.view_as
    return outcomes, final


async def _outcome(store: Any, call: Call, labels: dict[str, str]) -> object:
    args = () if call.row is None else (str(session_id(call.row)),)
    try:
        result = await getattr(store, call.method)(*args, **call.kwargs)
    except ValueError:  # pydantic's ValidationError included
        return "ValueError"
    if result is None:
        return None
    if call.method == "leave_view_as":
        row, ended_now = result
        return labels[str(row.id)], row.view_as, ended_now
    if call.method == "start_view_as_unit":  # (started, held): held reads refused here
        started, _held = result
        return None if started is None else (labels[str(started.id)], started.view_as)
    if isinstance(result, tuple):
        names = [labels[str(row.id)] for row in result]
        return tuple(sorted(names) if call.unordered else names)
    return labels[str(result.id)], result.view_as


def expected(scenario: Scenario) -> tuple[tuple[object, ...], dict[str, Any]]:
    """`play`'s result when the store honours the table: a row ends as its last applied write
    left it, and every other row as it was inserted."""
    final: dict[str, Any] = {label: row.view_as for label, row in scenario.rows.items()}
    for outcome in scenario.expect:
        if isinstance(outcome, tuple) and len(outcome) > 1 and isinstance(outcome[1], ViewAsState):
            final[outcome[0]] = outcome[1]
    return scenario.expect, final
