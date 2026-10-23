"""Lifecycle contract for the admin module (M21).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from candleviewer.admin.audited import audit_exempt, audited
from candleviewer.admin.errors import KekRewrapError, SigningKeyRotationError
from candleviewer.admin.models import KekRewrapResult
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.secrets import ExportKeyRotationError, KekRotationError, KekUnavailable

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.secrets import SecretsMetadata, SigningKeyRotator


class AdminService:
    """Empty scaffold for the M21 `admin` module lifecycle."""

    def __init__(
        self, secrets: SecretsMetadata | None = None, signing_keys: SigningKeyRotator | None = None
    ) -> None:
        self._started = False
        #: E27-T02 / C-3.2: M2 metadata only (verify KEK, counts-only re-wrap).
        self.secrets = secrets
        #: #889 S7: the audit export signing key's rotation, M2's capability (public keys only).
        self.signing_keys = signing_keys

    @audit_exempt("lifecycle")
    async def start(self, ctx: AppContext) -> None:
        """Start the module. No-op until the owning epic implements it."""
        self._started = True

    @audit_exempt("lifecycle")
    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. No-op scaffold."""
        self._started = False

    @audit_exempt("read")
    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="", status=status, detail="scaffold module — no real logic yet")

    @audited(
        "security.kek_rotation_refused",
        "security.kek_rotation_started",
        "security.kek_rotation_resumed",
        "security.kek_rotation_failed",
        "security.kek_rotation_incomplete",
        "security.kek_rotated",
        "security.credential_rewrapped",
    )
    async def rewrap_kek(
        self, environment: str, to_version: int, actor_user_id: str
    ) -> KekRewrapResult:
        """#2266 D1: one KEK re-wrap run for the Owner (`rewrapKek`), counts only. M2 checks the
        staged boot, audits a refusal, latches order entry and runs; this maps its errors to the
        contract's codes. Without M2 no refusal can be recorded: `audit_unavailable`. Called by
        `POST /admin/keys/kek-rewrap` (`api/admin_kek.py`), the Owner-only entry point."""
        if self.secrets is None:
            raise KekRewrapError("audit_unavailable")
        try:
            report = await self.secrets.rewrap_deks(
                to_version, environment=environment, actor_user_id=actor_user_id, actor_role="owner"
            )
        except KekUnavailable:
            raise KekRewrapError("kek_unavailable") from None
        except KekRotationError as exc:
            raise KekRewrapError(exc.code) from None
        return KekRewrapResult(
            run_id=report.run_id,
            environment=environment,
            from_version=report.from_version,
            to_version=report.to_version,
            resumed=report.resumed,
            rewrapped=report.rewrapped,
            remaining=report.remaining,
            failed=len(report.failed),
            complete=report.complete,
        )

    @audited(
        "security.audit_signing_key_rotated",
        "security.audit_signing_key_rotation_refused",
        "security.audit_signing_key_rotation_failed",
        "security.audit_signing_key_unavailable",
    )
    async def rotate_audit_signing_key(
        self,
        reason: str,
        *,
        actor_user_id: UUID,
        client_ref: UUID,
        client_body_sha256: str,
        export_running: Callable[[], bool],
    ) -> tuple[dict[str, dict[str, Any]], bool]:
        """#889 S7 (ADR-0039 decision 5): `rotateAuditSigningKey`'s rotation, run by M2 in 22's
        order, which records it. Its answer (the key made and the key retired, public records
        with M2's marks) and whether it is a repeat; else `SigningKeyRotationError` with the
        contract's code. Without M2 nothing can be recorded: `audit_unavailable`."""
        if self.signing_keys is None:
            raise SigningKeyRotationError("audit_unavailable")
        try:
            return await self.signing_keys.rotate(
                reason, actor_user_id=actor_user_id, client_ref=client_ref,
                client_body_sha256=client_body_sha256, export_running=export_running,
            )  # fmt: skip
        except ExportKeyRotationError as exc:
            code, wait = exc.code, exc.retry_after_s
        raise SigningKeyRotationError(code, wait)  # after the handler: nothing chained
