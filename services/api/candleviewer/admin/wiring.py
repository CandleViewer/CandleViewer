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
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from candleviewer.audit.actions import validate_action
from candleviewer.audit.lane_journal import key_id
from candleviewer.audit.models import AuditEmission, AuditOutcome, ExchangeEnv, Severity
from candleviewer.audit.redact import redact
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.service import AuditService, LaneKeyLoader
from candleviewer.audit.verify_job import AuditVerifyJob
from candleviewer.audit.verify_runner import VerifyRunner
from candleviewer.observability.metrics import Metrics
from candleviewer.secrets import (
    AuthKeyStore,
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
    "audit_lane_key_id",
    "audit_writer_sink",
    "build_audit_service",
    "build_audit_verify_job",
    "build_secrets_service",
    "export_secrets_metrics",
    "secrets_audit_row",
    "secrets_audit_sink",
    "system_event_redactor",
]
AuditHandle = AuditService
#: The scheduled verify run's port (#2111), so `app` can type an injected runner.
AuditVerifyRunner = VerifyRunner


#: The M2 records that page: a KEK that failed to load or re-wrap, and stranded rows (#2266).
_SECRETS_ERRORS = frozenset(
    {"security.kek_load_failed", "security.kek_rotation_failed", "security.kek_rows_stranded"}
)
#: An M2 refusal (#2266): stored as denied, at warning, as the other refusals are (C-12.8).
_SECRETS_REFUSED = "security.kek_rotation_refused"


def _secrets_audit_columns(action: str, fields: dict[str, str]) -> dict[str, Any]:
    """The audit columns of one M2 record, for the WAL sink and the row builder alike. Fields
    are ids only; the actor comes from the wiring-bound caller identity, never the borrower."""
    columns: dict[str, Any] = {
        "actor_label": f"{fields.get('actor_kind', 'system')}:{fields.get('actor_role', '')}",
        "actor_user_id": fields.get("actor_user_id"),
        "object_kind": "api_key" if "key_id" in fields else "kek",
        "object_id": fields.get("key_id"),
        "severity": Severity.ERROR if action in _SECRETS_ERRORS else Severity.INFO,
        "after_state": dict(fields),
    }
    if action == _SECRETS_REFUSED:
        columns |= {"outcome": AuditOutcome.DENIED, "severity": Severity.WARNING}
    return columns


def secrets_audit_sink(audit: AuditService) -> Callable[[str, dict[str, str]], Awaitable[None]]:
    """M2 audit port -> durable `AuditWriter.emit` (write-ahead)."""

    async def sink(action: str, fields: dict[str, str]) -> None:
        await audit.writer.emit(action, **_secrets_audit_columns(action, fields))

    return sink


def _utc_now() -> datetime:
    return datetime.now(UTC)


def secrets_audit_row(
    env: str, clock: Callable[[], datetime] = _utc_now
) -> Callable[[str, dict[str, str]], dict[str, Any]]:
    """M2 `(action, fields)` -> one `audit_log` record in the WAL's format, which the M10
    credential store inserts in the transaction of the change it records (#2266: a re-wrap's
    `security.credential_rewrapped`, an enrolment's `security.kek_enrolled`). The columns
    `secrets_audit_sink` writes, and what
    `AuditWriter.emit` does to a record: the action validated, the state redacted, a fresh
    `record_id` and the clock's `event_ts`; plus the process environment `env`. M2 passes only
    `(action, fields)`: neither M2 nor M10 imports `audit` (CONSTITUTION §3)."""
    process_env = ExchangeEnv(env)

    def build(action: str, fields: dict[str, str]) -> dict[str, Any]:
        columns = _secrets_audit_columns(validate_action(action), fields)
        columns["after_state"] = redact(columns["after_state"])
        emission = AuditEmission(
            record_id=uuid.uuid4(), action=action, env=process_env, event_ts=clock(), **columns
        )
        record: dict[str, Any] = json.loads(emission.model_dump_json())
        return record

    return build


def build_secrets_service(
    store: CredentialStore | None = None,
    kcv_store: KcvStore | None = None,
    audit: AuditService | None = None,
    auth_keys: AuthKeyStore | None = None,
) -> SecretsBundle:
    """Construct M2 once and split it into narrow capabilities. No I/O; the KEK is loaded in
    `start()`. Without an injected store (fake backend) every credential op fails closed. A KEK
    re-wrap run counts `auth_keys`, the environment's auth keyring, and is never complete
    without it (#3505)."""
    sink = secrets_audit_sink(audit) if audit is not None else None
    if store is None or kcv_store is None:
        svc = SecretsService(audit=sink)  # no store: fail closed, but still audited (C-2.9)
    else:
        svc = SecretsService(store=store, kcv_store=kcv_store, audit=sink, auth_keys=auth_keys)
    return SecretsBundle(
        SecretsLifecycleFacade(svc),
        SecretsMetadataFacade(svc),
        mint_borrower(svc, "exchange_adapter"),
        mint_candidate_keys(svc),
    )


def build_audit_service(
    repository: AuditRepository | None = None, *, lane_keys: LaneKeyLoader | None = None
) -> AuditHandle:
    """Construct M19. No I/O. With a repository (storage_backend=real, QA
    #1658) `start()` wires the real WAL-backed `AuditWriter`; without one it
    stays the scaffold. `start()` runs `lane_keys`, the composition root's
    lane key loader, once (ADR-0037 decision 6)."""
    return AuditService(repository, lane_keys=lane_keys)


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


def system_event_redactor() -> Callable[[dict[str, Any] | None], dict[str, Any] | None]:
    """The audit serializer that `system_events.details` pass through (`24-internal-schemas.md`
    15.4, `21-database-schema.md` 12), for the event writers the composition root builds: they
    may not import M19 themselves (C-3.3). No I/O."""
    return redact


def audit_lane_key_id(key: bytes) -> str:
    """The audit lane key's id (`24-internal-schemas.md` §15.6 `kid`), safe to log, for the
    composition root's key loader, which may not import M19 itself (C-3.3). No I/O."""
    return key_id(key)


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
