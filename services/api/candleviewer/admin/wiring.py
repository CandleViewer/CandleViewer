"""Factories for the protected modules the composition root must inject.

CONSTITUTION.md C-3.2 lets only M4/M21 import M2 (`secrets`) and C-3.3 lets
only M21/M23 read M19 (`audit`). The composition root (`candleviewer.app`)
is neither, so it never imports those packages: it asks this M21 module to
construct them and injects the returned instances into `AppContext`
(`docs/plan/20-architecture.md` Sec.6.1, "everything is injected").

The type aliases let `app` annotate its fields without a direct import edge.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from candleviewer.audit.models import Severity
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.service import AuditService
from candleviewer.audit.verify_job import AuditVerifyJob
from candleviewer.audit.verify_runner import VerifyRunner
from candleviewer.observability.metrics import Metrics
from candleviewer.secrets import (
    CandidateKeys,
    CredentialBorrower,
    CredentialStore,
    KcvStore,
    SecretsLifecycle,
    SecretsLifecycleFacade,
    SecretsMetadata,
    SecretsMetadataFacade,
    SecretsService,
    export_secrets_metrics,
    mint_borrower,
    mint_candidate_keys,
)
from candleviewer.settings import Settings

#: What `AppContext.secrets` holds: lifecycle + health only (C-3.2). `admin` is injected
#: `SecretsMeta`; M4 is injected the one `CredentialBorrower` minted here. Key import (#836) gets
#: `SecretsBundle.candidate_keys`, minted here too, so it imports no M2 module.
SecretsHandle = SecretsLifecycle
SecretsMeta = SecretsMetadata


@dataclass(frozen=True)
class SecretsBundle:
    """The four narrow capabilities of one `SecretsService` (built once, in wiring)."""

    lifecycle: SecretsLifecycle
    metadata: SecretsMetadata
    exchange_borrower: CredentialBorrower
    candidate_keys: CandidateKeys


__all__ = [
    "AuditHandle",
    "AuditVerifyRunner",
    "SecretsBundle",
    "SecretsHandle",
    "SecretsMeta",
    "audit_writer_sink",
    "build_audit_service",
    "build_audit_verify_job",
    "build_secrets_service",
    "export_secrets_metrics",
    "secrets_audit_sink",
]
AuditHandle = AuditService
#: The scheduled verify run's port (#2111), so `app` can type an injected runner.
AuditVerifyRunner = VerifyRunner


def secrets_audit_sink(audit: AuditService) -> Callable[[str, dict[str, str]], Awaitable[None]]:
    """M2 audit port -> durable `AuditWriter.emit` (write-ahead). Fields are ids only; the
    actor comes from the wiring-bound caller identity, never from the borrower."""

    async def sink(action: str, fields: dict[str, str]) -> None:
        await audit.writer.emit(
            action,
            actor_label=f"{fields.get('actor_kind', 'system')}:{fields.get('actor_role', '')}",
            actor_user_id=fields.get("actor_user_id"),
            object_kind="api_key" if "key_id" in fields else "kek",
            object_id=fields.get("key_id"),
            severity=(
                Severity.ERROR
                if action in ("security.kek_load_failed", "security.kek_rotation_failed")
                else Severity.INFO
            ),
            after_state=dict(fields),
        )

    return sink


def build_secrets_service(
    store: CredentialStore | None = None,
    kcv_store: KcvStore | None = None,
    audit: AuditService | None = None,
) -> SecretsBundle:
    """Construct M2 once and split it into narrow capabilities. No I/O; the KEK is loaded in
    `start()`. Without an injected store (fake backend) every credential op fails closed."""
    sink = secrets_audit_sink(audit) if audit is not None else None
    if store is None or kcv_store is None:
        svc = SecretsService(audit=sink)  # no store: fail closed, but still audited (C-2.9)
    else:
        svc = SecretsService(store=store, kcv_store=kcv_store, audit=sink)
    return SecretsBundle(
        SecretsLifecycleFacade(svc),
        SecretsMetadataFacade(svc),
        mint_borrower(svc, "exchange_adapter"),
        mint_candidate_keys(svc),
    )


def build_audit_service(repository: AuditRepository | None = None) -> AuditHandle:
    """Construct M19. No I/O. With a repository (storage_backend=real, QA
    #1658) `start()` wires the real WAL-backed `AuditWriter`; without one it
    stays the scaffold."""
    return AuditService(repository)


def build_audit_verify_job(
    audit: AuditService, settings: Settings, metrics: Metrics, runner: VerifyRunner | None
) -> AuditVerifyJob | None:
    """The start-up and nightly verify job (#2111), or `None` while no runner is wired (nothing
    runs or pages). No I/O; the lifespan starts it once the audit module is up."""
    if runner is None:
        return None
    return AuditVerifyJob(
        runner,
        lambda: audit.query.verify_slot,
        metrics,
        hour_utc=settings.audit_verify_nightly_hour_utc,
        deadline_s=settings.audit_verify_nightly_deadline_s,
    )


def _before(data: dict[str, str]) -> dict[str, Any] | None:
    raw = data.get("scope_before")
    return {"rule_scope": json.loads(raw)} if raw else None


def audit_writer_sink(writer: Any) -> Callable[[str, dict[str, str]], Awaitable[None]]:
    """Adapt `AuditWriter.emit` (durable, write-ahead) to the scope audit port."""
    names = {
        "rule_scope_denied": "rules.scope_denied",
        "rule_live_scope_armed": "rules.live_scope_armed",
        "rule_action_scope_denied": "rules.scope_denied",
    }

    async def sink(event: str, data: dict[str, str]) -> None:
        await writer.emit(
            names[event],
            actor_label=data.get("caller", "unknown"),
            actor_user_id=data.get("caller"),
            object_kind="rule_scope",
            object_id=data.get("account") or data.get("environment"),
            severity=Severity.ERROR if data.get("severity") == "high" else Severity.WARNING,
            before_state=_before(data),
            after_state={k: v for k, v in data.items() if k != "scope_before"},
        )

    return sink
