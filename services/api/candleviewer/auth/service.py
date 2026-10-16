"""Lifecycle contract for the auth module (M18).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. E09-S01
wires `LoginService` when a real `UserRepository` is injected (mirrors
`AuditService`'s "`is_active` until a real backend is wired" pattern);
without one (fake/CI-default backend) it stays the no-op scaffold so
`create_app()`/tests keep working without a database. E09-S02 additionally
wires `MfaService` when an `MfaRepository` is injected, using the same
`is_active` gate, and hands `LoginService` the same `MfaRepository` so it
can persist the `mfa_challenges` row the two-legged login flow shares.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from candleviewer.auth.break_glass_notice import BreakGlassEvents, BreakGlassNotice
from candleviewer.auth.envelope import LOCAL_KEY_REF, TotpEncryptor
from candleviewer.auth.errors import AuthServiceUnavailable
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.invite_service import InviteService
from candleviewer.auth.login_service import LoginService
from candleviewer.auth.mfa_service import MfaService
from candleviewer.auth.models import SessionRecord, UserRecord
from candleviewer.auth.session_service import (
    RevocationSink,
    SessionClass,
    SessionService,
    classify_session,
)
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.totp_skew import TotpSkewReporter
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.observability.health_probes import SystemEventWriter
from candleviewer.settings import Environment

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.auth.invite_repository import InviteRepository
    from candleviewer.auth.mfa_repository import MfaRepository
    from candleviewer.auth.repository import UserRepository
    from candleviewer.auth.session_repository import SessionRepository


class AuthService:
    """M18 `auth` module lifecycle.

    `login`/`mfa` are `None` until `start()` has wired a real backend;
    callers (the `api` router) must check `is_active`/`mfa_is_active`
    first."""

    def __init__(
        self,
        repository: UserRepository | None = None,
        *,
        pepper: str = "",
        mfa_repository: MfaRepository | None = None,
        totp_encryption_key: bytes | None = None,
        recovery_code_hmac_key: bytes | None = None,
        session_repository: SessionRepository | None = None,
        clock: Callable[[], datetime] | None = None,
        invite_repository: InviteRepository | None = None,
        system_events: SystemEventWriter | None = None,
        break_glass_events: BreakGlassEvents | None = None,
    ) -> None:
        self._started = False
        #: Where a TOTP clock-skew event goes (#2146); `None` still counts the metric.
        self._system_events = system_events
        self._invite_repository = invite_repository
        self._invites: InviteService | None = None
        #: One injected clock for login/MFA/session (QA #1658: the e2e test
        #: fixes time so TOTP codes and session deadlines are deterministic).
        self._clock = clock or _utc_now
        self._repository = repository
        self._pepper = pepper
        self._mfa_repository = mfa_repository
        self._totp_encryption_key = totp_encryption_key
        self._recovery_code_hmac_key = recovery_code_hmac_key
        self._session_repository = session_repository
        self._sessions: SessionService | None = None
        self._login: LoginService | None = None
        self._mfa: MfaService | None = None
        self._step_up: StepUpService | None = None
        #: #2272: where every session this module revokes is published (the
        #: WS `RevocationHub`); attached by the composition root.
        self._revocation_sink: RevocationSink | None = None
        self._skew_reporter: TotpSkewReporter | None = None
        #: E09-S11 (O4): the unresolved break-glass state behind the WS `system` notice.
        self._break_glass_notice = BreakGlassNotice(break_glass_events)

    @property
    def is_active(self) -> bool:
        return self._login is not None

    @property
    def login(self) -> LoginService:
        if self._login is None:
            raise RuntimeError("AuthService.start() has not wired a real backend")
        return self._login

    @property
    def mfa_is_active(self) -> bool:
        return self._mfa is not None

    @property
    def mfa(self) -> MfaService:
        if self._mfa is None:
            raise RuntimeError("AuthService.start() has not wired an MfaRepository")
        return self._mfa

    @property
    def step_up_is_active(self) -> bool:
        return self._step_up is not None

    @property
    def step_up(self) -> StepUpService:
        if self._step_up is None:
            raise RuntimeError("AuthService.start() has not wired step-up")
        return self._step_up

    @property
    def invites_is_active(self) -> bool:
        return self._invites is not None

    @property
    def invites(self) -> InviteService:
        if self._invites is None:
            raise RuntimeError("AuthService.start() has not wired invites")
        return self._invites

    @property
    def sessions_is_active(self) -> bool:
        return self._sessions is not None

    @property
    def sessions(self) -> SessionService:
        if self._sessions is None:
            raise RuntimeError("AuthService.start() has not wired a SessionRepository")
        return self._sessions

    @property
    def break_glass_notice(self) -> BreakGlassNotice:
        return self._break_glass_notice

    @property
    def enrolment_gate_is_active(self) -> bool:
        """#2295: sessions can be classified, because the session store and the user store
        are both wired. It is false only where no enrolment-only session can exist: without
        the session store nothing authenticates, and without the user store nobody signs in
        (`login` needs it), so no session is minted on a password there. `build_auth_service`
        wires both or neither (`tests/unit/storage/test_auth_repositories_sqlalchemy.py`).
        Sessions wired without a user store are a wiring fault that the step-up guard
        already answers on its routes; this gate stays inert there rather than refuse every
        request (#2771 keeps the non-dangerous routes served). Once active, a store failure
        fails closed (`classify`)."""
        return self._sessions is not None and self._repository is not None

    async def classify(self, session: SessionRecord) -> SessionClass:
        """The class of a resolved session from its user's state, read now and never cached
        (#2295). Raises when no user store is wired and lets a store failure propagate:
        the HTTP guard and the WS authenticator turn either into a refusal (fail closed)."""
        if self._repository is None:
            raise AuthServiceUnavailable("no user store wired; the session cannot be classified")
        user = await self._repository.find_by_id(str(session.user_id))
        return classify_session(session, user, now=self._clock())

    async def find_user(self, user_id: str) -> UserRecord | None:
        """The live user *user_id* as the store reads it now (#2295: enrolment checks the
        caller's confirmed methods here, never a cached copy). Raises when no user store
        is wired."""
        if self._repository is None:
            raise AuthServiceUnavailable("no user store wired")
        return await self._repository.find_by_id(user_id)

    def attach_revocation_sink(self, sink: RevocationSink) -> None:
        """Publish every session this module revokes to *sink*
        (`23-ws-protocol.md` §9.5). Looked up per publish, so it reaches the
        services whether it is attached before or after `start()`."""
        self._revocation_sink = sink

    async def _publish_revocation(self, session_id: str, reason: str) -> None:
        if self._revocation_sink is not None:
            await self._revocation_sink(session_id, reason)

    async def start(self, ctx: AppContext) -> None:
        """Start the module. Wires `LoginService`/`MfaService` only when a
        concrete repository was injected by the composition root;
        otherwise stays the no-op scaffold. `auth` never imports a storage
        driver (ADR-0003 import-linter contract)."""
        if self._repository is not None:
            self._login = LoginService(
                self._repository,
                Hasher(pepper=self._pepper),
                mfa_repository=self._mfa_repository,
                clock=self._clock,
            )
        if self._session_repository is not None:
            self._sessions = SessionService(
                self._session_repository,
                Hasher(pepper=self._pepper),
                clock=self._clock,
                publish_revocation=self._publish_revocation,
            )
        if self._mfa_repository is not None:
            # `totp_encryption_key` stands in for the real M2 KEK wiring
            # (see `envelope.py`'s module docstring for why M18 cannot
            # import `candleviewer.secrets` itself). PR #1618 review finding
            # 3: a process-local fallback key must never silently reach a
            # live/demo deployment — it is not persisted, so seeds become
            # undecryptable after any restart, and nothing stops it being
            # reused outside dev. `E27-T02` (the M2 credential broker /
            # KEK loader) is the tracked follow-up that replaces this key
            # with a real `SecretsService`-resolved one; until it lands,
            # the fallback is refused outside `Environment.DEMO`/`TESTNET`
            # so a `live`-configured process fails fast at startup instead
            # of quietly running with an ephemeral key.
            key = self._totp_encryption_key
            if key is None:
                if ctx is not None and ctx.settings.environment is Environment.LIVE:
                    raise RuntimeError(
                        "AuthService: no totp_encryption_key configured for a live "
                        "environment; a process-local fallback key would make TOTP "
                        "seeds undecryptable after restart (see E27-T02, envelope.py)"
                    )
                key = _process_local_key()
            # Recovery-code HMAC key (PR #1618 security review, blocking 1):
            # same custody boundary and same live fail-fast rule as the TOTP
            # key above; tracked for real M2 wiring by E27-T02.
            rc_key = self._recovery_code_hmac_key
            if rc_key is None:
                if ctx is not None and ctx.settings.environment is Environment.LIVE:
                    raise RuntimeError(
                        "AuthService: no recovery_code_hmac_key configured for a live "
                        "environment; a process-local fallback key would make stored "
                        "recovery codes unverifiable after restart (see E27-T02)"
                    )
                rc_key = _process_local_key()
            encryptor = TotpEncryptor(key, key_ref=LOCAL_KEY_REF)
            skew_reporter = TotpSkewReporter(
                self._system_events, clock=lambda: self._clock().timestamp()
            )
            skew_reporter.start()  # publishes held reports once due; `stop()` ends it
            self._skew_reporter = skew_reporter
            self._mfa = MfaService(
                self._mfa_repository,
                encryptor,
                recovery_code_key=rc_key,
                clock=self._clock,
                skew_reporter=skew_reporter,
            )
            if self._invite_repository is not None:
                self._invites = InviteService(
                    self._invite_repository,
                    Hasher(pepper=self._pepper),
                    self._mfa,
                    clock=self._clock,
                )
            if self._session_repository is not None and self._repository is not None:
                # E09-S04: one process-wide instance (per-session state is
                # in-memory, matching the B16 per-process interpreter).
                self._step_up = StepUpService(
                    self._mfa_repository,
                    self._session_repository,
                    encryptor,
                    self._repository,
                    Hasher(pepper=self._pepper),
                    publish_revocation=self._publish_revocation,
                    clock=self._clock,
                    skew_reporter=skew_reporter,
                )
        await self._break_glass_notice.start()  # read before cv-api serves, then every minute
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. No-op scaffold."""
        self._login = None
        self._mfa = None
        self._invites = None
        if self._skew_reporter is not None:
            await self._skew_reporter.stop()
            self._skew_reporter = None
        await self._break_glass_notice.stop()
        if self._step_up is not None:
            await self._step_up.stop()
        self._step_up = None
        self._sessions = None
        self._started = False

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        detail = "" if self.is_active else "scaffold module — no repository wired"
        return HealthReport(module="auth", status=status, detail=detail)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _process_local_key() -> bytes:
    return os.urandom(32)
