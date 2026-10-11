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
from typing import Any

from candleviewer.audit.models import Severity
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.service import AuditService
from candleviewer.secrets._metrics import export_secrets_metrics
from candleviewer.secrets.service import KcvStore, SecretsService
from candleviewer.secrets.store import CredentialStore

SecretsHandle = SecretsService

#: The composition root may not import M2 (C-3.2); it gets the metrics exporter from here.
__all__ = [
    "AuditHandle",
    "SecretsHandle",
    "audit_writer_sink",
    "build_audit_service",
    "build_secrets_service",
    "export_secrets_metrics",
    "secrets_audit_sink",
]
AuditHandle = AuditService


def secrets_audit_sink(audit: AuditService) -> Callable[[str, dict[str, str]], Awaitable[None]]:
    """M2 audit port -> durable `AuditWriter.emit` (write-ahead). Fields are ids only."""

    async def sink(action: str, fields: dict[str, str]) -> None:
        await audit.writer.emit(
            action,
            actor_label=f"system:{fields.get('caller_module', 'secrets')}",
            object_kind="api_key" if "key_id" in fields else "kek",
            object_id=fields.get("key_id"),
            severity=Severity.ERROR if action == "security.kek_load_failed" else Severity.INFO,
            after_state=dict(fields),
        )

    return sink


def build_secrets_service(
    store: CredentialStore | None = None,
    kcv_store: KcvStore | None = None,
    audit: AuditService | None = None,
) -> SecretsHandle:
    """Construct M2. No I/O; the KEK is loaded in `start()`. Without an injected store (fake
    backend) the broker stays disabled and every credential operation fails closed."""
    if store is None or audit is None:
        return SecretsService()
    return SecretsService(store=store, kcv_store=kcv_store, audit=secrets_audit_sink(audit))


def build_audit_service(repository: AuditRepository | None = None) -> AuditHandle:
    """Construct M19. No I/O. With a repository (storage_backend=real, QA
    #1658) `start()` wires the real WAL-backed `AuditWriter`; without one it
    stays the scaffold."""
    return AuditService(repository)


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
