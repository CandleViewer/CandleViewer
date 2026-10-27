"""SR-022 Owner alert on recovery-code use (#2496).

`POST /auth/mfa/recovery` moves `auth_recovery_codes_used_total` once per spent code. Its
`auth.recovery_code_used` audit row is written ahead (#2344), so a failing audit sink stops the
recovery before the code is spent and cannot hide a use. The series is served on the scraped
registry with `env`, where `AuthRecoveryCodeUsed` (`infra/prometheus/alerts/system_page.yml`)
reads it and pages the Owner through Alertmanager. Refused attempts never move it, including a
request that lost the race for its code or its challenge: the spend is one transaction (#2344),
so that request spends nothing and is refused and audited as `auth.mfa_failed`. It has no
label, so the alert cannot name the user; the audit row does.

The route runs over the real `MfaService` and the in-memory repository, with a session leg
that mints the recovery's enrolment-only session (#2344).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, generate_latest

from candleviewer.api.auth import LoginServiceLike, make_auth_router
from candleviewer.app import create_app
from candleviewer.audit.errors import AuditError
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.metrics import AUTH_EXPORTED_NAMES
from candleviewer.auth.mfa_service import CHALLENGE_ATTEMPT_CAP, MfaService, _hash_token
from candleviewer.auth.models import UserRecord, UserStatus
from candleviewer.auth.recovery_codes import hash_recovery_code
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings
from tests.unit.api._fakes import Identity, WriterLane, sessions
from tests.unit.auth.auth_fakes import no_wait

from .mfa_fakes import FakeMfaRepository

SERIES = "auth_recovery_codes_used_total"
_RC_KEY = b"k" * 32
_NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
_CODE = "2345-6789-ABCD-EFGH-JKMN-PQRS-TUVW"


class _Auth:
    """`AuthServiceLike` with the real MFA leg and the session leg; the route never reaches
    login."""

    is_active = True
    sessions_is_active = True

    def __init__(self, mfa: MfaService, *, mfa_active: bool = True) -> None:
        self.mfa = mfa
        self.mfa_is_active = mfa_active
        self.sessions = sessions(now=_NOW)

    @property
    def login(self) -> LoginServiceLike:
        raise AssertionError("not reached by /auth/mfa/recovery")

    async def find_user(self, user_id: str) -> UserRecord:
        """A user who must re-enrol: recovery fails closed without `mfa_required` (C-12.2)."""
        return UserRecord(
            id=uuid.UUID(user_id),
            username="recovering",
            email="recovering@example.test",
            password_hash="unused",
            password_algo_params={},
            status=UserStatus.ACTIVE,
            mfa_required=True,
            failed_login_count=0,
            locked_until=None,
        )


class _Writer:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.actions: list[str] = []

    async def emit(self, action: str, **_fields: Any) -> None:
        if self.fail:
            raise AuditError("audit sink unavailable")
        self.actions.append(action)


class _Audit:
    is_active = True

    def __init__(self, *, fail: bool = False) -> None:
        self.writer = _Writer(fail=fail)
        self.lane = WriterLane(self)  # ADR-0037's façade as its fallback: each record to the writer


def _used() -> float:
    return float(REGISTRY.get_sample_value(SERIES) or 0.0)


class _LostCodeRace(FakeMfaRepository):
    """A concurrent request spent the same code between the check and the commit (#2344)."""

    async def complete_recovery(
        self, user_id: str, *, challenge_id: str, code_id: str, now: datetime
    ) -> bool | None:
        self.recovery_codes[code_id]["used_at"] = now.isoformat()  # the winner's commit
        return await super().complete_recovery(
            user_id, challenge_id=challenge_id, code_id=code_id, now=now
        )


class _LostChallengeRace(FakeMfaRepository):
    """A concurrent request satisfied the same challenge first (#2344: one transaction)."""

    async def complete_recovery(
        self, user_id: str, *, challenge_id: str, code_id: str, now: datetime
    ) -> bool | None:
        won = self.challenges[challenge_id].model_copy(update={"satisfied_at": now})
        self.challenges[challenge_id] = won  # the winner's commit
        return await super().complete_recovery(
            user_id, challenge_id=challenge_id, code_id=code_id, now=now
        )


async def _repo_with(
    *codes: str, repo: FakeMfaRepository | None = None
) -> tuple[FakeMfaRepository, uuid.UUID]:
    repo, user_id = (FakeMfaRepository() if repo is None else repo), uuid.uuid4()
    await repo.replace_recovery_codes(
        str(user_id), code_hashes=tuple(hash_recovery_code(c, key=_RC_KEY) for c in codes)
    )
    for token in ("t1", "t2"):
        await repo.create_challenge(
            str(user_id),
            purpose="login",
            mfa_token_hash=_hash_token(token),
            expires_at=_NOW + timedelta(minutes=5),
        )
    return repo, user_id


def _client(repo: FakeMfaRepository, audit: _Audit, *, mfa_active: bool = True) -> TestClient:
    mfa = MfaService(
        repo,
        TotpEncryptor(os.urandom(32)),
        recovery_code_key=_RC_KEY,
        clock=lambda: _NOW,
        sleep=no_wait,
    )
    app = FastAPI()
    app.include_router(
        make_auth_router(
            _Auth(mfa, mfa_active=mfa_active),
            audit,
            identity=Identity(),
            csrf=CsrfCodec(b"\x05" * 32),
        )
    )
    return TestClient(app, raise_server_exceptions=False)


def _recover(client: TestClient, token: str, code: str) -> int:
    body = {"mfa_token": token, "recovery_code": code}
    status: int = client.post("/auth/mfa/recovery", json=body).status_code
    return status


async def test_recovery_route_accepted_code_counts_once_beside_its_audit_row() -> None:
    repo, _ = await _repo_with(_CODE)
    audit = _Audit()
    before = _used()

    assert _recover(_client(repo, audit), "t1", _CODE) == 200

    assert _used() == before + 1
    assert audit.writer.actions == ["auth.recovery_code_used", "auth.session_created"]


async def test_recovery_route_replayed_code_is_refused_and_not_counted_again() -> None:
    repo, _ = await _repo_with(_CODE, "XYZ2-3456-789A-BCDE-FGHJ-KMNP-QRST")
    client = _client(repo, _Audit())
    before = _used()
    assert _recover(client, "t1", _CODE) == 200

    assert _recover(client, "t2", _CODE) == 401

    assert _used() == before + 1


async def test_recovery_route_wrong_code_leaves_the_counter_unchanged() -> None:
    repo, _ = await _repo_with(_CODE)
    before = _used()

    assert _recover(_client(repo, _Audit()), "t1", "WRNG-CODE-0000") == 401

    assert _used() == before


async def test_recovery_route_exhausted_codes_leave_the_counter_unchanged() -> None:
    repo, _ = await _repo_with()
    before = _used()

    assert _recover(_client(repo, _Audit()), "t1", _CODE) == 401

    assert _used() == before


async def test_recovery_route_without_an_mfa_backend_leaves_the_counter_unchanged() -> None:
    repo, _ = await _repo_with(_CODE)
    before = _used()

    # #2344: the operation's 401; nothing is checked or spent without every backend.
    assert _recover(_client(repo, _Audit(), mfa_active=False), "t1", _CODE) == 401

    assert _used() == before


async def test_recovery_route_spends_and_counts_nothing_when_the_audit_write_fails() -> None:
    """#2344: the records are written ahead, so a failing audit sink stops the recovery before
    the code is spent; there is no use to hide, and none is counted."""
    repo, user_id = await _repo_with(_CODE)
    before = _used()

    assert _recover(_client(repo, _Audit(fail=True)), "t1", _CODE) == 401

    assert _used() == before
    assert await repo.count_unused_recovery_codes(str(user_id)) == 1


async def test_recovery_route_lost_consume_race_is_refused_and_not_counted() -> None:
    repo, _ = await _repo_with(_CODE, repo=_LostCodeRace())
    audit = _Audit()
    before = _used()

    assert _recover(_client(repo, audit), "t1", _CODE) == 401

    assert _used() == before
    # The records written ahead, then the one that voids them (#2344).
    assert audit.writer.actions == [
        "auth.recovery_code_used",
        "auth.session_created",
        "auth.mfa_failed",
    ]


async def test_recovery_route_lost_challenge_race_spends_no_code_and_is_not_counted() -> None:
    """#2344 supersedes the DoR update on #2496: the code is spent in the transaction that
    satisfies the challenge, so the losing request spends nothing. It is refused and audited
    as `auth.mfa_failed`; only the request that won the race counts."""
    repo, user_id = await _repo_with(_CODE, repo=_LostChallengeRace())
    audit = _Audit()
    before = _used()

    assert _recover(_client(repo, audit), "t1", _CODE) == 401

    assert _used() == before
    # The records written ahead, then the one that voids them (#2344).
    assert audit.writer.actions == [
        "auth.recovery_code_used",
        "auth.session_created",
        "auth.mfa_failed",
    ]
    assert await repo.count_unused_recovery_codes(str(user_id)) == 1


async def test_recovery_route_locked_challenge_refuses_a_valid_code_without_counting_it() -> None:
    repo, user_id = await _repo_with(_CODE)
    challenge = await repo.find_open_challenge_by_token_hash(_hash_token("t1"))
    assert challenge is not None
    for _ in range(CHALLENGE_ATTEMPT_CAP):
        await repo.record_challenge_attempt(str(challenge.id))
    audit = _Audit()
    before = _used()

    assert _recover(_client(repo, audit), "t1", _CODE) == 401

    assert _used() == before
    assert audit.writer.actions == ["auth.mfa_failed"]
    assert await repo.count_unused_recovery_codes(str(user_id)) == 1


def test_recovery_codes_used_is_catalogued_live_and_exported() -> None:
    spec = next(s for s in CATALOGUE if s.name == SERIES)

    assert (spec.kind, spec.labels, spec.status, spec.exported) == ("counter", (), "live", True)
    assert SERIES in AUTH_EXPORTED_NAMES


def test_recovery_codes_used_series_exists_before_the_first_use() -> None:
    """`increase()` needs a 0 sample before the first use, or that use is never seen."""
    assert REGISTRY.get_sample_value(SERIES) is not None


def test_create_app_serves_recovery_codes_used_on_the_scraped_registry() -> None:
    app = create_app(Settings(environment=Environment.DEMO))

    text = generate_latest(app.state.app_context.metrics).decode()

    assert f'{SERIES}{{env="demo"}} ' in text
