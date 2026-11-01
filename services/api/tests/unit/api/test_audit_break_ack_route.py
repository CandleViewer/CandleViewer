"""`acknowledgeAuditChainBreak` (#2904 PR 2; 22 `POST /admin/audit/chain-breaks/{firstBadId}/
acknowledge`, 04 §7.2.2 row 49c): Owner only, the no-grace `killswitch` step-up bound to the
request, the named break, written ahead; the halt lifts only on a written acknowledgement."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.audit import make_audit_router
from candleviewer.api.step_up import HANDLER_GATED_ROUTES
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.break_halt import (
    ACK_DENIED,
    ACKNOWLEDGED,
    AuditBreakHalt,
    AuditBreakHaltService,
    BreakIdentity,
)
from candleviewer.audit.models import ChainBreakKind, VerifyResult
from candleviewer.auth.errors import StepUpRequired
from candleviewer.auth.step_up import StepUpChallenge

_PATH = "/admin/audit/chain-breaks/{}/acknowledge"
_BREAK = BreakIdentity(41207, "entry_hash_mismatch")
_BODY = {"kind": "entry_hash_mismatch", "reason": "Restored row 41207 from the mirror"}


class _Writer:
    """The audit writer; each record notes whether the halt was still engaged as it was written."""

    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict[str, Any], bool]] = []
        self.fail_on: set[str] = set()
        self.halt: AuditBreakHalt | None = None

    async def emit(self, action: str, **fields: Any) -> None:
        if action in self.fail_on:
            raise RuntimeError("audit down")
        engaged = self.halt is not None and self.halt.engaged
        self.emitted.append((action, fields, engaged))

    def actions(self) -> list[str]:
        return [action for action, _, _ in self.emitted]


class _Audit:
    is_active = True

    def __init__(self) -> None:
        self.writer = _Writer()
        self.query: Any = None


class _Resolver:
    def __init__(self, principal: AuditPrincipal | None) -> None:
        self.principal = principal

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        return self.principal


class _StepUp:
    """The step-up seams: `grant` holds the one-shot `killswitch` grant (any fingerprint) or
    none; every consume names the class and the request it binds."""

    step_up_is_active = sessions_is_active = True

    def __init__(self, *, grant: bool) -> None:
        self.step_up = self.sessions = self
        self.grant = grant
        self.consumed: list[tuple[str, str]] = []
        self.spent: list[uuid.UUID] = []

    async def consume_single_use(
        self, session_id: str, action_class: str, *, fingerprint: str
    ) -> StepUpChallenge:
        self.consumed.append((action_class, fingerprint))
        if not self.grant:
            raise StepUpRequired(action_class)
        challenge = await self.record_pending(session_id, action_class, fingerprint=fingerprint)
        self.spent.append(challenge.challenge_id)
        return challenge

    async def record_pending(
        self, session_id: str, action_class: str, *, fingerprint: str | None = None
    ) -> StepUpChallenge:
        expires = datetime.now(UTC) + timedelta(minutes=2)
        return StepUpChallenge(uuid.uuid4(), action_class, expires, fingerprint)


def _broken(identity: BreakIdentity) -> VerifyResult:
    unknown = identity.kind == "unknown"
    return VerifyResult(
        verified=False,
        entries_checked=identity.first_bad_id,
        first_bad_id=None if unknown else identity.first_bad_id,
        kind=None if unknown else ChainBreakKind(identity.kind),
        checked_at=datetime(2026, 10, 31, tzinfo=UTC),
        from_id=1,
        to_id=100000,
        anchor_hash="0" * 64,
        last_hash="a" * 64,
    )


def _principal(*, owner: bool = True, permissions: frozenset[str] | None = None) -> AuditPrincipal:
    held = frozenset({"killswitch:write", "audit:read"}) if permissions is None else permissions
    return AuditPrincipal(
        user_id=uuid.uuid4(),
        username="owner" if owner else "manager",
        permissions=held,
        session_id=uuid.uuid4(),
        ip="10.0.0.7",
        request_id=uuid.uuid4(),
        is_owner=owner,
    )


class _Rig:
    def __init__(
        self,
        principal: AuditPrincipal | None,
        *,
        grant: bool = True,
        breaks: tuple[BreakIdentity, ...] = (_BREAK,),
        wired: bool = True,
    ) -> None:
        self.audit, self.principal = _Audit(), principal
        self.halt = AuditBreakHalt(unread=False)
        self.audit.writer.halt = self.halt
        self.shown: list[str | None] = []
        self.service = AuditBreakHaltService(self.halt, cast(Any, self.audit), on_change=self._show)
        for identity in breaks:  # each tripped and recorded as a verifier does
            result = _broken(identity)
            owed = self.service.trip(result)
            assert owed == identity
            asyncio.run(self.service.record_trip(owed, result, trigger="on_demand"))
        self.audit.writer.emitted.clear()  # the halt records: each test reads what follows
        self.step_up = _StepUp(grant=grant)
        app = FastAPI()
        app.include_router(
            make_audit_router(
                cast(Any, self.audit),
                _Resolver(principal),
                step_up=cast(Any, self.step_up),
                break_ack=self.service if wired else None,
            )
        )
        self.client = TestClient(app)

    async def _show(self, reason: str | None) -> None:
        self.shown.append(reason)

    def post(self, first_bad_id: object = 41207, body: Any = None) -> Any:
        payload = _BODY if body is None else body
        return self.client.post(_PATH.format(first_bad_id), json=payload)


def test_ack_by_the_owner_with_a_step_up_is_written_ahead_then_lifts_the_halt() -> None:
    rig = _Rig(_principal())
    response = rig.post()
    assert response.status_code == 200, response.text
    assert response.json() == {
        "first_bad_id": 41207,
        "kind": "entry_hash_mismatch",
        "halted": False,
    }
    assert response.headers["Cache-Control"] == "no-store"
    [(action, fields, engaged_at_write)] = rig.audit.writer.emitted
    assert action == ACKNOWLEDGED
    assert engaged_at_write  # written ahead: the halt still stood while the record was written
    principal = rig.principal
    assert principal is not None
    assert (fields["session_id"], fields["actor_ip"], fields["request_id"]) == (
        principal.session_id, principal.ip, principal.request_id
    )  # fmt: skip
    assert (fields["actor_user_id"], fields["object_id"]) == (
        principal.user_id,
        "41207:entry_hash_mismatch",
    )
    assert fields["reason"] == _BODY["reason"]
    [spent] = rig.step_up.spent  # the record names the spent grant, as the other no-grace handlers
    assert fields["after_state"]["challenge_id"] == str(spent)
    assert not rig.halt.engaged and rig.shown == ["audit_chain_break", None]
    assert [cls for cls, _ in rig.step_up.consumed] == ["killswitch"]


def test_another_break_still_held_keeps_order_entry_halted() -> None:
    other = BreakIdentity(90000, "prev_hash_mismatch")
    rig = _Rig(_principal(), breaks=(_BREAK, other))
    response = rig.post()
    assert (response.status_code, response.json()["halted"]) == (200, True)
    assert rig.halt.breaks == (other,)


@pytest.mark.parametrize(
    ("principal", "reason"),
    [
        (_principal(owner=False), "owner_only"),  # a Manager holding killswitch:write (IDOR)
        (_principal(owner=False, permissions=frozenset({"orders:read"})), "missing_permission"),
    ],
    ids=["manager_with_killswitch_write", "viewer_without_it"],
)
def test_anyone_but_the_owner_is_forbidden_recorded_and_never_challenged(
    principal: AuditPrincipal, reason: str
) -> None:
    rig = _Rig(principal)
    response = rig.post()
    assert (response.status_code, response.json()["code"]) == (403, "forbidden")
    [(action, fields, _)] = rig.audit.writer.emitted
    assert action == "admin.audit_denied" and fields["reason"].startswith(reason)
    assert rig.step_up.consumed == [] and rig.halt.engaged


def test_no_session_is_401_and_nothing_is_written() -> None:
    rig = _Rig(None)
    assert rig.post().status_code == 401
    assert rig.audit.writer.emitted == [] and rig.halt.engaged


def test_without_the_step_up_it_is_challenged_with_the_killswitch_class_and_the_halt_stays() -> (
    None
):
    rig = _Rig(_principal(), grant=False)
    response = rig.post()
    body = response.json()
    assert (response.status_code, body["code"], body["action_class"]) == (
        403, "step_up_required", "killswitch"
    )  # fmt: skip
    assert "41207:entry_hash_mismatch" in body["action_summary"]
    assert rig.audit.writer.emitted == [] and rig.halt.engaged


def test_the_grant_is_bound_to_the_request_it_validated() -> None:
    rig = _Rig(_principal(), grant=False)
    rig.post()
    rig.post(body=_BODY | {"reason": "another reason"})
    rig.post(first_bad_id=41208)
    fingerprints = {fingerprint for _, fingerprint in rig.step_up.consumed}
    assert len(fingerprints) == 3


@pytest.mark.parametrize(
    ("first_bad_id", "kind"),
    [(41207, "prev_hash_mismatch"), (41208, "entry_hash_mismatch")],
    ids=["wrong_kind", "unknown_break"],
)
def test_a_break_not_held_engaged_is_409_recorded_as_ack_denied(
    first_bad_id: int, kind: str
) -> None:
    rig = _Rig(_principal())
    response = rig.post(first_bad_id, _BODY | {"kind": kind})
    assert (response.status_code, response.json()["code"]) == (409, "conflict")
    [(action, fields, _)] = rig.audit.writer.emitted
    assert (action, fields["reason"]) == (ACK_DENIED, "not_engaged")
    assert rig.halt.engaged


def test_an_already_acknowledged_break_is_409() -> None:
    rig = _Rig(_principal())
    assert rig.post().status_code == 200
    assert rig.post().status_code == 409


@pytest.mark.parametrize(
    ("first_bad_id", "body", "field"),
    [
        (41207, {"kind": "made_up", "reason": "valid reason"}, "kind"),
        (41207, {"kind": "entry_hash_mismatch", "reason": "no"}, "reason"),
        (41207, {"kind": "entry_hash_mismatch"}, "reason"),
        (41207, {"kind": "entry_hash_mismatch", "reason": "   "}, "reason"),
        (41207, {"kind": "entry_hash_mismatch", "reason": " a \t "}, "reason"),
        (41207, {"kind": "entry_hash_mismatch", "reason": "line one\nline two"}, "reason"),
        (41207, {**_BODY, "extra": 1}, "(unknown)"),
        ("abc", _BODY, "firstBadId"),
        (2**63, _BODY, "firstBadId"),
    ],
    ids=[
        "unknown_kind",
        "short_reason",
        "no_reason",
        "blank_reason",
        "mostly_blank_reason",
        "unprintable_reason",
        "extra_member",
        "not_an_id",
        "over_int64",
    ],
)
def test_an_invalid_request_is_422_before_any_challenge(
    first_bad_id: object, body: dict[str, Any], field: str
) -> None:
    rig = _Rig(_principal())
    response = rig.post(first_bad_id, body)
    assert (response.status_code, response.json()["code"]) == (422, "validation_failed")
    assert field in {error["field"] for error in response.json()["errors"]}
    assert rig.step_up.consumed == [] and rig.audit.writer.emitted == []


def test_a_body_over_the_cap_is_422_unread() -> None:
    rig = _Rig(_principal())
    response = rig.post(body=_BODY | {"reason": "x" * 4096})
    assert (response.status_code, response.json()["errors"][0]["rule"]) == (422, "max_body_bytes")
    assert rig.step_up.consumed == []


def test_a_break_reported_without_a_kind_is_acknowledged_as_unknown() -> None:
    rig = _Rig(_principal(), breaks=(BreakIdentity(0, "unknown"),))
    response = rig.post(0, {"kind": "unknown", "reason": "no kind was reported"})
    assert response.status_code == 200 and not rig.halt.engaged


def test_an_acknowledgement_that_cannot_be_written_is_503_and_the_halt_stays() -> None:
    rig = _Rig(_principal())
    rig.audit.writer.fail_on.add(ACKNOWLEDGED)
    response = rig.post()
    assert (response.status_code, response.json()["code"]) == (503, "audit_unavailable")
    assert rig.halt.engaged and rig.shown == ["audit_chain_break"]


def test_unwired_acknowledgement_is_503_and_lifts_nothing() -> None:
    rig = _Rig(_principal(), wired=False)
    response = rig.post()
    assert response.status_code == 503 and rig.halt.engaged
    assert rig.step_up.consumed == []


def test_the_route_is_registered_as_handler_gated_with_the_killswitch_class() -> None:
    row = ("POST", "/admin/audit/chain-breaks/{firstBadId}/acknowledge", "killswitch")
    assert row in HANDLER_GATED_ROUTES
