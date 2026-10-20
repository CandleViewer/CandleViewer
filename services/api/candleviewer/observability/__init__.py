"""observability module (M24).

Structured logging, redaction filters, metrics, tracing.

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1.

`E04-T01` (structlog JSON logging + handler-level redaction) is implemented.
Metrics/tracing land in later E04 tickets.
"""

from __future__ import annotations

from candleviewer.observability.body_logging import BodyLoggingGate
from candleviewer.observability.context import bind_context, spawn, spawn_child
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.observability.logging import RedactionFilter, configure_logging
from candleviewer.observability.secret_type import Secret

__all__ = [
    "BodyLoggingGate",
    "HealthReport",
    "HealthStatus",
    "RedactionFilter",
    "Secret",
    "bind_context",
    "configure_logging",
    "spawn",
    "spawn_child",
]
