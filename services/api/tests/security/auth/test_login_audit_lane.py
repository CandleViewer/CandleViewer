"""#2914 PR C (ADR-0037 Q2, Amendment 2): on the composed app, each outcome and refusal row of the
login routes goes to the audit lane's façade, and the write-ahead records of their mints stay on
the audit writer (U42).

`_stack.py`'s app, with a writer that refuses the rows a test picks, as `AuditWriter.emit` does
while its WAL is unwritable, and `_Lane`, an in-memory façade: a row whose action and outcome
`LANE_ACTIONS` admits is journaled unless the lane is held, and any other row, or every row while
it is held, goes to the writer, its fallback (decision 1). The writer refusing a row the lane
takes: the answer is the one a working sink gets and nothing is counted lost. The lane held too:
the same answer, and the row is counted lost and logged. A mint whose write-ahead record the
writer refuses mints nothing, and the lane is never handed that record. No network, no sleeps.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
import structlog

from candleviewer.audit.actions import LANE_ACTIONS
from candleviewer.audit.models import AuditOutcome
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.errors import MfaEnrollmentNotFound, RecoveryCodeInvalid, UserDisabled
from candleviewer.auth.models import UserStatus
from tests.csrf_helpers import csrf_headers
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

from ._stack import PW, Stack, open_stack

_LOST, _FAILED = "auth.login_audit.outcome_lost", "auth.login_failed"
_PEER = "127.0.0.1"  # the stack's client, the address MeshOnly admits and every row records
_WRONG_CODE = "0000-0000-0000-0000"  # no recovery code: they are generated, never this
Pick = Callable[[str, dict[str, Any]], bool]


class _Lane:
    """`AuditService.lane` without its files (ADR-0037 decision 1): `rows` holds what it journaled,
    `asked` every action it was handed."""

    def __init__(self, stack: Stack) -> None:
        self.stack, self.held = stack, False
        self.asked: list[str] = []
        self.rows: list[dict[str, Any]] = []

    async def emit(self, action: str, **row: Any) -> None:
        self.asked.append(action)
        admitted = LANE_ACTIONS.get(action)
        if (
            self.held
            or admitted is None
            or row.get("outcome", AuditOutcome.SUCCESS) not in admitted[1]
        ):
            await self.stack.audit.emit(action, **row)  # the writer, read per call
            return
        self.rows.append({"action": action, **row})


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    with open_stack(monkeypatch) as s:
        yield s


@pytest.fixture
def lane(stack: Stack) -> _Lane:
    facade = _Lane(stack)
    stack.state.app_context.audit._facade = facade  # what `AuditService.start()` wires
    return facade


def _refuse(stack: Stack, monkeypatch: pytest.MonkeyPatch, picks: Pick) -> list[str]:
    """From now on the writer refuses each row *picks*; returns the actions it refused."""
    emit, refused = stack.audit.emit, list[str]()

    async def refusing(action: str, **row: Any) -> None:
        if picks(action, row):
            refused.append(action)
            raise AuditUnavailable("audit WAL unavailable: OSError")
        await emit(action, **row)

    monkeypatch.setattr(stack.audit, "emit", refusing)
    return refused


def _lost(action: str) -> float:
    return Stack.in_process("auth_audit_outcome_lost_total", action=action)


def _user(stack: Stack, **update: Any) -> tuple[uuid.UUID, bytes]:
    """`alice`, with `PW` and a confirmed TOTP method, her user row then given *update*."""
    uid, seed = stack.add_user("alice")
    _update(stack, uid, **update)
    return uid, seed


def _update(stack: Stack, uid: uuid.UUID, **update: Any) -> None:
    if update:
        stack.users.add(stack.users.users[str(uid)].model_copy(update=update))


def _sessions(stack: Stack) -> FakeSessionRepository:
    return cast(FakeSessionRepository, stack.auth._session_repository)


def _live(stack: Stack, uid: uuid.UUID) -> set[uuid.UUID]:
    return {view.id for view in stack.call(stack.auth.sessions.list_sessions, str(uid))}


def _login(stack: Stack, password: str = PW) -> Any:
    stack.client.cookies.clear()
    return stack.client.post("/auth/login", json={"identifier": "alice", "password": password})


def _verify(stack: Stack, token: str, code: str) -> Any:
    stack.client.cookies.clear()
    body = {"mfa_token": token, "method": "totp", "code": code}
    return stack.client.post("/auth/mfa/verify", json=body)


def _wrong_totp(stack: Stack, seed: bytes) -> str:
    """Six digits that no step of *seed*'s accepted window (+/-1) produces."""
    window = {stack.code(seed, offset) for offset in (-1, 0, 1)}
    return next(code for code in ("000000", "000001", "000002", "000003") if code not in window)


def _codes(stack: Stack, uid: uuid.UUID) -> tuple[str, ...]:
    return tuple(stack.call(stack.auth.mfa.regenerate_recovery_codes, str(uid)).recovery_codes)


def _recover(stack: Stack, token: str, code: str) -> Any:
    stack.client.cookies.clear()
    return stack.client.post("/auth/mfa/recovery", json={"mfa_token": token, "recovery_code": code})


def _failing(error: Exception) -> Callable[..., Any]:
    async def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    return fail


def _enrolling(stack: Stack) -> tuple[uuid.UUID, dict[str, str], str, bytes]:
    """A user who must enrol, signed in enrolment-only, with a TOTP method pending: her id, the
    bearer and SR-041 headers, the method and its seed."""
    uid, _ = _user(stack, mfa_methods=())
    access = _login(stack).json()["tokens"]["access_token"]
    record = stack.call(stack.auth.sessions.peek_access_token, access)
    headers = {
        "Authorization": f"Bearer {access}",
        **csrf_headers(stack.state.csrf_codec, record.id),
    }
    stack.client.cookies.clear()
    enrolled = stack.client.post("/auth/mfa/enroll", headers=headers, json={"method": "totp"})
    secret = parse_qs(urlparse(enrolled.json()["otpauth_uri"]).query)["secret"][0]
    seed = base64.b32decode(secret + "=" * (-len(secret) % 8))
    return uid, headers, enrolled.json()["method_id"], seed


def _confirm(stack: Stack, headers: dict[str, str], method_id: str, code: str) -> Any:
    stack.client.cookies.clear()
    body = {"method_id": method_id, "code": code}
    return stack.client.post("/auth/mfa/enroll/confirm", headers=headers, json=body)


# -- the routes' outcome and refusal rows ---------------------------------------------------------


def _wrong_password(stack: Stack, mp: pytest.MonkeyPatch) -> Any:
    _user(stack)
    return _login(stack, "wrong-guess")


def _account(stack: Stack, mp: pytest.MonkeyPatch, **update: Any) -> Any:
    _user(stack, **update)
    return _login(stack)


def _wrong_second_factor(stack: Stack, mp: pytest.MonkeyPatch) -> Any:
    _, seed = _user(stack)
    return _verify(stack, _login(stack).json()["mfa_token"], _wrong_totp(stack, seed))


def _disabled_at_the_mint(stack: Stack, mp: pytest.MonkeyPatch) -> Any:
    """#2911: disabled since the password step; the mint refuses (`_audit_refusal`)."""
    uid, seed = _user(stack)
    token = _login(stack).json()["mfa_token"]
    _sessions(stack).user_statuses[str(uid)] = UserStatus.DISABLED
    return _verify(stack, token, stack.code(seed))


def _unminted_at_the_mint(stack: Stack, mp: pytest.MonkeyPatch) -> Any:
    """A store failure at the MFA step's mint, after its `auth.session_created`: the 500 stands."""
    _, seed = _user(stack)
    token = _login(stack).json()["mfa_token"]
    mp.setattr(stack.auth.sessions, "mint", _failing(_UNMINTED))
    return _verify(stack, token, stack.code(seed))


def _enrolment_only_disabled(stack: Stack, mp: pytest.MonkeyPatch) -> Any:
    uid, _ = _user(stack, mfa_methods=())
    _sessions(stack).user_statuses[str(uid)] = UserStatus.DISABLED
    return _login(stack)


def _recovery(
    stack: Stack,
    mp: pytest.MonkeyPatch,
    *,
    code: str | None = None,
    user: dict[str, Any] | None = None,
    patch: tuple[object, str, Exception] | None = None,
) -> Any:
    """`/auth/mfa/recovery` with a fresh code (or *code*), the user given *user* after the
    password step, and *patch* (an object, its method, the error it raises) applied."""
    uid, _ = _user(stack)
    codes, token = _codes(stack, uid), _login(stack).json()["mfa_token"]
    _update(stack, uid, **(user or {}))
    if patch is not None:
        target, name, error = patch
        mp.setattr(target, name, _failing(error))
    return _recover(stack, token, codes[0] if code is None else code)


def _exhausted(stack: Stack, mp: pytest.MonkeyPatch) -> Any:
    uid, _ = _user(stack)
    stack.call(
        cast(FakeMfaRepository, stack.auth._mfa_repository).replace_recovery_codes,
        str(uid),
        code_hashes=(),
    )
    return _recover(stack, _login(stack).json()["mfa_token"], _WRONG_CODE)


def _spend(error: Exception) -> Callable[[Stack, pytest.MonkeyPatch], Any]:
    return lambda stack, mp: _recovery(
        stack, mp, patch=(stack.auth.mfa, "complete_recovery", error)
    )


def _mint_after_the_spend(error: Exception) -> Callable[[Stack, pytest.MonkeyPatch], Any]:
    return lambda stack, mp: _recovery(
        stack, mp, patch=(stack.auth.sessions, "mint_enrolment_only", error)
    )


def _unplanned(stack: Stack, mp: pytest.MonkeyPatch) -> Any:
    """A recovery whose plan missed the later of the user's two sessions (minted between its list
    and its revoke-all): that one ends with its own `unplanned` row, after the commit."""
    uid, seed = _user(stack)
    codes = _codes(stack, uid)
    for _ in range(2):
        reply = stack.sign_in("alice", seed)
    late = stack.call(stack.auth.sessions.peek_access_token, reply.json()["tokens"]["access_token"])
    listed = stack.auth.sessions.list_sessions

    async def without_the_late_one(user_id: str, **kwargs: Any) -> tuple[Any, ...]:
        return tuple(view for view in await listed(user_id, **kwargs) if view.id != late.id)

    token = _login(stack).json()["mfa_token"]
    mp.setattr(stack.auth.sessions, "list_sessions", without_the_late_one)
    return _recover(stack, token, codes[0])


def _confirming(error: Exception | None) -> Callable[[Stack, pytest.MonkeyPatch], Any]:
    """The confirm with a wrong code (*error* None), or with the commit raising *error*."""

    def act(stack: Stack, mp: pytest.MonkeyPatch) -> Any:
        _, headers, method_id, seed = _enrolling(stack)
        if error is None:
            return _confirm(stack, headers, method_id, _wrong_totp(stack, seed))
        mp.setattr(stack.auth.mfa, "complete_enrollment", _failing(error))
        return _confirm(stack, headers, method_id, stack.code(seed))

    return act


def _named(action: str) -> Pick:
    return lambda name, _row: name == action


@dataclass(frozen=True)
class _Row:
    act: Callable[[Stack, pytest.MonkeyPatch], Any]
    action: str  # the outcome row's
    status: int  # the answer a working sink gets
    picks: Pick | None = None  # the row, when its action alone does not tell it apart


_DISABLED, _UNMINTED = UserDisabled("disabled"), OSError("session store unavailable")
_ROWS: dict[str, _Row] = {
    "login_wrong_password": _Row(_wrong_password, "auth.login_failed", 401),
    "login_disabled": _Row(partial(_account, status=UserStatus.DISABLED), "auth.login_failed", 403),
    "login_locked": _Row(
        lambda s, mp: _account(s, mp, locked_until=s.clock.now + timedelta(hours=1)),
        "auth.account_locked",
        423,
    ),
    "login_password_step": _Row(_account, "auth.login", 200),
    "verify_wrong_code": _Row(_wrong_second_factor, "auth.mfa_failed", 401),
    "verify_disabled": _Row(_disabled_at_the_mint, "auth.login_failed", 401),
    "verify_unminted": _Row(_unminted_at_the_mint, "auth.mfa_failed", 500),
    "sign_in_disabled": _Row(_enrolment_only_disabled, "auth.login_failed", 403),
    "recovery_exhausted": _Row(_exhausted, "auth.recovery_codes_exhausted", 401),
    "recovery_wrong_code": _Row(partial(_recovery, code=_WRONG_CODE), "auth.mfa_failed", 401),
    "recovery_not_required": _Row(
        partial(_recovery, user={"mfa_required": False}), "auth.mfa_failed", 401
    ),
    "recovery_disabled": _Row(
        partial(_recovery, user={"status": UserStatus.DISABLED}), "auth.login_failed", 401
    ),
    "recovery_spend_disabled": _Row(_spend(_DISABLED), "auth.login_failed", 401),
    "recovery_spend_lost_race": _Row(_spend(RecoveryCodeInvalid("lost")), "auth.mfa_failed", 401),
    "recovery_spend_store_error": _Row(_spend(OSError("timeout")), "auth.mfa_failed", 401),
    "recovery_mint_disabled": _Row(_mint_after_the_spend(_DISABLED), "auth.login_failed", 401),
    "recovery_unminted": _Row(_mint_after_the_spend(_UNMINTED), "auth.mfa_failed", 401),
    "recovery_unplanned": _Row(
        _unplanned,
        "auth.session_revoked",
        200,
        lambda name, row: name == "auth.session_revoked" and row.get("after_state") is not None,
    ),
    "confirm_wrong_code": _Row(_confirming(None), "auth.mfa_failed", 422),
    "confirm_lost_race": _Row(_confirming(MfaEnrollmentNotFound("won")), "auth.mfa_failed", 422),
    "confirm_disabled": _Row(_confirming(_DISABLED), "auth.login_failed", 401),
    "confirm_store_error": _Row(_confirming(OSError("timeout")), "auth.mfa_failed", 500),
}


@pytest.mark.parametrize("name", sorted(_ROWS))
def test_a_row_the_writer_refuses_is_journaled_and_the_answer_stands(
    stack: Stack, lane: _Lane, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    row = _ROWS[name]
    picks = row.picks or _named(row.action)
    refused, lost = _refuse(stack, monkeypatch, picks), _lost(row.action)

    reply = row.act(stack, monkeypatch)

    assert reply.status_code == row.status
    journaled = [r for r in lane.rows if picks(r["action"], r)]
    assert [r["action"] for r in journaled] == [row.action]
    assert journaled[0]["actor_ip"] == _PEER  # the row's forensic address (C-2.9)
    assert refused == [] and _lost(row.action) == lost


@pytest.mark.parametrize("name", sorted(_ROWS))
def test_a_row_the_lane_and_the_writer_both_refuse_is_counted_lost_and_the_answer_stands(
    stack: Stack, lane: _Lane, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    row = _ROWS[name]
    lane.held = True  # every append refused (`held`), so each row falls back to the writer
    refused, lost = _refuse(stack, monkeypatch, row.picks or _named(row.action)), _lost(row.action)

    with structlog.testing.capture_logs() as logs:
        reply = row.act(stack, monkeypatch)

    assert reply.status_code == row.status
    assert refused == [row.action] and _lost(row.action) - lost == 1
    assert [e for e in logs if e["event"] == _LOST] == [
        {"event": _LOST, "log_level": "error", "action": row.action, "error": "AuditUnavailable"}
    ]


def test_a_recovery_that_mints_nothing_names_every_session_it_ended(
    stack: Stack, lane: _Lane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0037 Amendment 1's carry: `auth.recovery.completed_unminted` names the session the
    plan missed too, beside the planned ones, and its own row went to the lane first."""
    monkeypatch.setattr(stack.auth.sessions, "mint_enrolment_only", _failing(_UNMINTED))
    with structlog.testing.capture_logs() as logs:
        reply = _unplanned(stack, monkeypatch)

    assert (reply.status_code, reply.json()["title"]) == (401, "Recovery failed")
    (planned,) = [r["session_id"] for r in stack.audit.of("auth.session_revoked")]  # the writer's
    (late,) = [r["session_id"] for r in lane.rows if r["action"] == "auth.session_revoked"]
    (event,) = [e for e in logs if e["event"] == "auth.recovery.completed_unminted"]
    assert event["revoked_session_ids"] == [str(planned), str(late)]


def test_an_unknown_user_and_a_wrong_password_get_one_answer_while_both_refuse_the_row(
    stack: Stack, lane: _Lane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """U8 (SR-014) during an outage: with the lane held and the writer refusing, an unknown
    identifier and a wrong password still get the same answer, its bytes and its headers apart
    from the request id, and each row is counted lost."""
    _user(stack)
    lane.held = True
    refused, lost = _refuse(stack, monkeypatch, _named(_FAILED)), _lost(_FAILED)
    stack.client.cookies.clear()
    unknown = stack.client.post("/auth/login", json={"identifier": "mallory", "password": PW})
    wrong = _login(stack, "wrong-guess")

    def answer(reply: Any) -> tuple[int, bytes, dict[str, str]]:
        headers = {k: v for k, v in reply.headers.items() if k != "x-correlation-id"}
        return reply.status_code, reply.content, headers

    assert answer(unknown) == answer(wrong) and unknown.status_code == 401
    assert refused == [_FAILED, _FAILED] and _lost(_FAILED) - lost == 2


# -- U42: a mint's write-ahead records stay on the writer -----------------------------------------

Mint = Callable[[Stack], tuple[Callable[[], Any], uuid.UUID]]


def _sign_in_mint(stack: Stack) -> tuple[Callable[[], Any], uuid.UUID]:
    uid, _ = _user(stack, mfa_methods=())
    return partial(_login, stack), uid


def _verify_mint(stack: Stack) -> tuple[Callable[[], Any], uuid.UUID]:
    uid, seed = _user(stack)
    token = _login(stack).json()["mfa_token"]
    return lambda: _verify(stack, token, stack.code(seed)), uid


def _recovery_mint(stack: Stack) -> tuple[Callable[[], Any], uuid.UUID]:
    uid, seed = _user(stack)
    codes = _codes(stack, uid)
    stack.sign_in("alice", seed)  # a live session for the plan to end
    token = _login(stack).json()["mfa_token"]
    return lambda: _recover(stack, token, codes[0]), uid


def _confirm_mint(stack: Stack) -> tuple[Callable[[], Any], uuid.UUID]:
    uid, headers, method_id, seed = _enrolling(stack)
    return lambda: _confirm(stack, headers, method_id, stack.code(seed)), uid


_MINTS: dict[str, Mint] = {
    "sign_in": _sign_in_mint,
    "verify": _verify_mint,
    "recovery": _recovery_mint,
    "confirm": _confirm_mint,
}


@pytest.mark.parametrize(
    ("mint", "record", "status"),
    [
        ("sign_in", "auth.login", 503),
        ("sign_in", "auth.session_created", 503),
        ("verify", "auth.mfa_verified", 401),
        ("verify", "auth.session_created", 401),  # written ahead of the mint since PR C
        ("recovery", "auth.recovery_code_used", 401),
        ("recovery", "auth.session_revoked", 401),
        ("recovery", "auth.session_created", 401),
        ("confirm", "auth.mfa_enrolled", 503),
        ("confirm", "auth.recovery_codes_regenerated", 503),
        ("confirm", "auth.session_revoked", 503),
        ("confirm", "auth.session_created", 503),
    ],
)
def test_a_mints_write_ahead_record_never_reaches_the_lane_so_its_refusal_mints_nothing(
    stack: Stack, lane: _Lane, monkeypatch: pytest.MonkeyPatch, mint: str, record: str, status: int
) -> None:
    """U42: the lane admits `auth.login`, `auth.recovery_code_used` and `auth.session_revoked`,
    but a mint's write-ahead records go to the writer by call site, so the mint fails closed while
    the sink refuses one of them however willing the lane is (ADR-0037 decision 3)."""
    act, uid = _MINTS[mint](stack)
    live, asked = _live(stack, uid), len(lane.asked)
    refused = _refuse(stack, monkeypatch, _named(record))

    reply = act()

    assert reply.status_code == status and refused == [record]
    assert _live(stack, uid) == live  # nothing minted or revoked (C-2.9)
    assert lane.asked[asked:] == []
