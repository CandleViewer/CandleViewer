"""Composition root (M1 + Sec.6, `docs/plan/20-architecture.md`).

Builds `AppContext` and the FastAPI application. "No module constructs its
own dependencies; everything is injected, which makes every module
unit-testable with fakes" (Sec.6.1).

This ticket (E02-T05) wires the frozen `AppContext`, a minimal supervisor
that starts/stops modules in the documented order, and a FastAPI factory
exposing only `/healthz`, `/readyz` and build-info. Every other module here
is a scaffold (no real logic) — the fields exist so E02-T06's import-linter
contracts and every later epic have a concrete injection point.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, cast

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from candleviewer.accounts.service import AccountsService
from candleviewer.admin.service import AdminService
from candleviewer.admin.wiring import (
    AuditHandle,
    SecretsBundle,
    SecretsHandle,
    audit_writer_sink,
    build_audit_service,
    build_secrets_service,
    export_secrets_metrics,
)
from candleviewer.alerts.dispatcher import AlertDispatcher, default_adapters
from candleviewer.alerts.evaluator import AlertEvaluator, AlertMetrics
from candleviewer.alerts.lifecycle import AlertCharts
from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER, alert_deliver_dedup_key
from candleviewer.alerts.service import AlertsService
from candleviewer.api import (
    make_audit_router,
    make_auth_router,
    make_funding_router,
    make_health_report_router,
    make_health_router,
    make_instruments_router,
    make_log_level_router,
    make_market_router,
    make_orderbook_router,
    make_rules_router,
    make_ticker_router,
    make_trades_router,
)
from candleviewer.api.alerts import make_alerts_router
from candleviewer.api.audit_budget import AuditBudgetFlushTask, AuditRecordBudget
from candleviewer.api.audit_limiter import AuditQueryLimiter
from candleviewer.api.audit_principal import SessionAuditPrincipalResolver
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.csrf import CsrfMiddleware, RefusalAuditTracker
from candleviewer.api.deny_by_default import (
    assert_app_routes_declared,
    declared_operations,
    make_deny_undeclared_dependency,
)
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.api.hotkey_audit import make_hotkey_audit_router
from candleviewer.api.invites import make_invites_router
from candleviewer.api.market_bars import make_market_bars_router
from candleviewer.api.market_coverage import make_data_coverage_router
from candleviewer.api.onboarding import make_onboarding_router
from candleviewer.api.onboarding_checklist import StepResult, bybit_key_restriction
from candleviewer.api.recorder_admin import AdminJobStore, make_recorder_admin_router
from candleviewer.api.rules_actor import SessionRulesActorResolver, make_rules_audit
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.api.sessions import make_session_router
from candleviewer.api.step_up import make_read_only_guard, make_step_up_router
from candleviewer.api.support_bundle import make_support_bundle_router
from candleviewer.api.telemetry import SessionKeyResolver, make_telemetry_router
from candleviewer.api.users import SnapshotResolver, UserRoleStore, make_users_router
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.metrics import export_auth_metrics
from candleviewer.auth.models import (
    InviteRecord,
    MfaChallengeRecord,
    MfaMethodRecord,
    SessionRecord,
    UserRecord,
)
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.auth.session_service import access_token_expires_at
from candleviewer.bars.limits import QUERY_TIMEOUT_S
from candleviewer.bars.metrics import export_bars_metrics
from candleviewer.bars.reader import BarReader, tape_time_bar_reader
from candleviewer.bars.service import BarsService
from candleviewer.bars_wiring import wire_bars
from candleviewer.book.service import BookService
from candleviewer.bus.models import Topic
from candleviewer.bus.service import BusService
from candleviewer.domain.events import InstrumentUpdatedEvent
from candleviewer.exchange.base.instruments import InstrumentsFetcher
from candleviewer.exchange.base.models import TickerEvent, TradeEvent
from candleviewer.exchange.base.service import ExchangeBaseService

# Composition root: wires the one concrete exchange adapter (C-2.2).
# nosemgrep: cv-adapter-isolation reason=B5-b owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.funding_wiring import wire_funding
from candleviewer.health_wiring import (
    HealthSystemPublisher,
    PgSystemEventReader,
    PgSystemEventWriter,
    WriteBehindLike,
    register_bars_probe,
    register_bars_writer_probe,
    register_ingestion_probe,
    register_public_ws_probe,
    register_real_probes,
    register_secrets_probe,
    register_write_behind_probe,
)
from candleviewer.import_wiring import build_import_runner
from candleviewer.ingestion.book_supervisor import B14BookSupervisor
from candleviewer.ingestion.clock import ClockGuard, ServerTimeFetcher, rest_client_fetcher
from candleviewer.ingestion.connection import MAX_FRAME_BYTES, ConnectionManager
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from candleviewer.ingestion.kline_backfill import KlineBackfillService, KlineFetcher
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.kline_read import KlineReadService, RecordingStart
from candleviewer.ingestion.metrics import export_ingestion_metrics, ingest_enabled
from candleviewer.ingestion.planner import SubscriptionPlanner
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy
from candleviewer.ingestion.rejection import EventWindow, corrected_now_us
from candleviewer.ingestion.service import IngestionService
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import TradeStream
from candleviewer.ingestion.watchdog import StalenessWatchdog
from candleviewer.journal.service import JournalService
from candleviewer.net import (
    BindingSelfCheck,
    CidrAllowList,
    MeshOnlyMiddleware,
    MeshSelfCheckScheduler,
    ReadOnlyGate,
    SystemTopicPublisher,
    net_binding_safe,
    real_socket_enumerator,
    register_system_topic_subscriber,
)
from candleviewer.net.system_topic import client_notice
from candleviewer.observability.correlation import CorrelationMiddleware
from candleviewer.observability.health_metrics import bind_health_metrics
from candleviewer.observability.health_probes import HealthRegistry
from candleviewer.observability.latency import StageRecorder
from candleviewer.observability.log_level import LogLevelOverrides
from candleviewer.observability.metrics import CollectorRegistry, Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.observability.service import ObservabilityService
from candleviewer.observability.support_bundle import filter_config
from candleviewer.observability.support_bundle_wiring import build_support_bundle_service
from candleviewer.observability.telemetry import SessionRateLimiter, TelemetrySink
from candleviewer.oms.service import OmsService
from candleviewer.orderbook_wiring import BookStream
from candleviewer.orderflow.service import OrderflowService
from candleviewer.paper.service import PaperService
from candleviewer.recorder.coverage import CoverageService
from candleviewer.recorder.metrics import current_write_backlog_rows
from candleviewer.recorder.service import RecorderService
from candleviewer.replay.service import ReplayService
from candleviewer.risk.service import RiskService
from candleviewer.rolloff_wiring import build_rolloff_job
from candleviewer.rules.service import RulesService
from candleviewer.rules_store_pg import PostgresRuleStore
from candleviewer.settings import Environment, Settings, get_settings
from candleviewer.statechart.bindings.b16_session import set_audit_sink as set_b16_audit_sink
from candleviewer.statechart.gateway import GatewayOverloadedError
from candleviewer.storage.cold.archive_import import FileImportLedger
from candleviewer.storage.cold.compaction_run import compact_all
from candleviewer.storage.cold.compactor import Compactor
from candleviewer.storage.cold.kline_reader import ParquetKlineReader
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.observability import LoggingSystemEventSink
from candleviewer.storage.cold.scrub import ScrubTask
from candleviewer.storage.cold.watermarks import FileWatermarkStore
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.wiring import QuestDbRowSink
from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import (
    SqlAlchemyAlertDeliveryRepository,
)
from candleviewer.storage.repositories.alert_dispatch_sqlalchemy import (
    SqlAlchemyAlertDispatchStore,
)
from candleviewer.storage.repositories.alert_firing_sqlalchemy import SqlAlchemyAlertFiringStore
from candleviewer.storage.repositories.alerts_sqlalchemy import SqlAlchemyAlertRepository
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.instruments_sqlalchemy import (
    SqlAlchemyInstrumentsRepository,
)
from candleviewer.storage.repositories.invites_sqlalchemy import SqlAlchemyInviteRepository
from candleviewer.storage.repositories.mfa_sqlalchemy import SqlAlchemyMfaRepository
from candleviewer.storage.repositories.onboarding_sqlalchemy import SqlAlchemyOnboardingStore
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.rows import (
    BookDeltaRow,
    BookSnapshotRow,
    KlineRow,
    TickerRow,
    TradeRow,
)
from candleviewer.storage.repositories.rules_sqlalchemy import SqlAlchemyRulesRepository
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource
from candleviewer.storage.repositories.sessions_sqlalchemy import (
    SqlAlchemySessionRepository,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository
from candleviewer.storage.retention.alert_tasks import AlertDeliveriesPurgeTask, AlertGaugeTask
from candleviewer.storage.retention.kline_boundary import (
    KlineBoundaryRefreshTask,
    KlineHotBoundary,
)
from candleviewer.storage.retention.policy import RetentionPolicy, RetentionRule
from candleviewer.storage.retention.rule_prune import RulePruneTask
from candleviewer.storage.retention.schedule import RetentionSchedule
from candleviewer.storage.service import StorageService
from candleviewer.ws.gateway import Authenticate, GatewayHub, make_ws_router
from candleviewer.ws.metrics import export_cvwb_metrics, export_ws_metrics
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub
from candleviewer.ws.service import WsService
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import (
    IngestionUpstreamSink,
    KillSwitchView,
    WsEvents,
    WsRuntime,
    default_snapshot_router,
    ingestion_streams,
)


@dataclass(frozen=True)
class AppContext:
    """Everything a module needs, injected — never a global (Sec.6.1).

    Fields mirror `docs/plan/20-architecture.md` Sec.6.1: settings, bus,
    storage clients, key vault, metric registry, clock guard, and the module
    instances. Storage clients/key vault/clock guard are not yet implemented
    (owned by later epics) so they are omitted here rather than faked with a
    wrong shape; `metrics` (a real `CollectorRegistry`) and every M2-M24
    module's `service.py` scaffold are wired now so downstream tickets have a
    concrete constructor to extend.
    """

    settings: Settings
    metrics: CollectorRegistry

    secrets: SecretsHandle
    exchange_base: ExchangeBaseService
    exchange_bybit: ExchangeBybitService
    bus: BusService
    ingestion: IngestionService
    book: BookService
    bars: BarsService
    orderflow: OrderflowService
    storage: StorageService
    recorder: RecorderService
    replay: ReplayService
    accounts: AccountsService
    oms: OmsService
    rules: RulesService
    paper: PaperService
    risk: RiskService
    auth: AuthService
    audit: AuditHandle
    journal: JournalService
    admin: AdminService
    alerts: AlertsService
    observability: ObservabilityService
    ws: WsService

    # E09-T04: Tailscale-only reachability guard (US-ONB-008). `oms` never
    # imports `candleviewer.net` directly (outside its §3 allow-list); this
    # is the one instance it is injected with, structurally typed as
    # `oms.validator.ReadOnlyCheck` so no import edge is created.
    oms_read_only_gate: ReadOnlyGate
    # Owns the boot + hourly re-check loop (AC5, "drift after resume").
    # `services/api/candleviewer/main.py`'s lifespan runs `run_once()` once
    # at startup (the boot check) then `start()` for the hourly loop, and
    # `stop()` on shutdown.
    mesh_self_check: MeshSelfCheckScheduler
    # QA defect #1578 blocker 1: the one production subscriber wiring
    # `oms_read_only_gate` transitions onto the `system` WS topic
    # (`23-ws-protocol.md` §6) so the mandatory blocking banner is actually
    # published, not merely mechanically possible via `ReadOnlyGate.subscribe`.
    mesh_system_topic_publisher: SystemTopicPublisher


class _LazyAuditEmitter:
    """Resolves `audit.writer` per call: it only exists once `AuditService.start()` ran."""

    def __init__(self, audit: AuditHandle) -> None:
        self._audit = audit

    async def emit(self, action: str, **kwargs: Any) -> None:
        await self._audit.writer.emit(action, **kwargs)


def _decode_key(name: str, secret: Any) -> bytes | None:
    if secret is None:
        return None
    try:
        key = bytes.fromhex(secret.get_secret_value())
    except ValueError as exc:
        raise ValueError(f"{name} must be hex-encoded") from exc
    if len(key) != 32:
        raise ValueError(f"{name} must decode to exactly 32 bytes, got {len(key)}")
    return key


def build_auth_service(
    settings: Settings, *, clock: Callable[[], datetime] | None = None
) -> AuthService:
    """QA #1658: wire `AuthService` to Postgres when `storage_backend="real"`
    (no I/O at construction: the engine connects lazily). With the fake
    backend it stays the no-op scaffold so `create_app()` needs no database.
    Live refuses to start (any backend) without pepper + key material."""
    totp = settings.auth_totp_key_hex
    rc = settings.auth_recovery_hmac_key_hex
    pepper = settings.auth_pepper.get_secret_value()
    real = settings.storage_backend == "real"
    if settings.environment is Environment.LIVE or real:
        if totp is None or rc is None:
            raise ValueError(
                "CV_AUTH_TOTP_KEY_HEX and CV_AUTH_RECOVERY_HMAC_KEY_HEX are required "
                "(live or storage_backend=real); refusing to start auth (C-12 TOTP)"
            )
        if not pepper:
            raise ValueError(
                "a non-empty CV_AUTH_PEPPER is required (live or storage_backend=real); "
                "refusing to start auth"
            )
    totp_key = _decode_key("CV_AUTH_TOTP_KEY_HEX", totp)
    rc_key = _decode_key("CV_AUTH_RECOVERY_HMAC_KEY_HEX", rc)
    if not real:
        return AuthService()
    relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "auth")
    return AuthService(
        SqlAlchemyUserRepository(
            relational, _record_factory(UserRecord), clock=clock or (lambda: datetime.now(UTC))
        ),
        pepper=settings.auth_pepper.get_secret_value(),
        mfa_repository=SqlAlchemyMfaRepository(
            relational, _record_factory(MfaMethodRecord), _record_factory(MfaChallengeRecord)
        ),
        totp_encryption_key=totp_key,
        recovery_code_hmac_key=rc_key,
        session_repository=SqlAlchemySessionRepository(relational, _record_factory(SessionRecord)),
        clock=clock,
        invite_repository=SqlAlchemyInviteRepository(relational, _record_factory(InviteRecord)),
    )


def build_csrf_codec(settings: Settings) -> CsrfCodec:
    """#2090 (SR-041): the dedicated CSRF HMAC key, loaded exactly like the
    other auth keys (`_decode_key`, 32-byte hex). Required on live or the real
    backend, and it must differ from the TOTP / recovery keys. Otherwise (fake
    backend, dev/CI) a process-local random key is used, with a warning: tokens
    then die with the process, which only forces a cookie re-issue via
    `GET /auth/session`."""
    current = settings.auth_csrf_key_hex
    if current is None and (
        settings.environment is Environment.LIVE or settings.storage_backend == "real"
    ):
        raise ValueError(
            "CV_AUTH_CSRF_KEY_HEX is required (live or storage_backend=real); "
            "refusing to start auth (SR-041)"
        )
    key = _decode_key("CV_AUTH_CSRF_KEY_HEX", current)
    previous = _decode_key("CV_AUTH_CSRF_PREVIOUS_KEY_HEX", settings.auth_csrf_previous_key_hex)
    others = {
        k
        for k in (
            _decode_key("CV_AUTH_TOTP_KEY_HEX", settings.auth_totp_key_hex),
            _decode_key("CV_AUTH_RECOVERY_HMAC_KEY_HEX", settings.auth_recovery_hmac_key_hex),
        )
        if k is not None
    }
    if {k for k in (key, previous) if k is not None} & others:
        raise ValueError(
            "CV_AUTH_CSRF_KEY_HEX / CV_AUTH_CSRF_PREVIOUS_KEY_HEX must be a dedicated key, "
            "not the TOTP or recovery key (SR-041)"
        )
    if key is None:
        structlog.get_logger(__name__).warning(
            "auth.csrf_key_ephemeral", detail="CV_AUTH_CSRF_KEY_HEX unset; process-local key"
        )
        key = os.urandom(32)
    return CsrfCodec(key, (previous,) if previous is not None else ())


def build_identity_provider(settings: Settings) -> SqlAlchemyIdentityProvider | None:
    """QA #1658: the SQL `User`/permissions read path for `/auth/session` and
    the post-MFA `AuthenticatedResponse`; `None` (routes fail closed with 501)
    on the fake backend."""
    if settings.storage_backend != "real":
        return None
    return SqlAlchemyIdentityProvider(
        SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "identity")
    )


def _build_audit(settings: Settings) -> AuditHandle:
    """QA #1658 (C-2.9): the real hash-chained audit sink on the real backend."""
    if settings.storage_backend != "real":
        return build_audit_service()
    return build_audit_service(
        SqlAlchemyAuditRepository(
            SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "audit"),
            read_slots=settings.audit_query_global_max_concurrent,
        )
    )


def _gate_notices(ctx: AppContext) -> list[dict[str, Any]]:
    gate = ctx.oms_read_only_gate
    if not gate.is_read_only:
        return []
    return [client_notice(True, gate.reason_code)]


def _build_secrets(settings: Settings, audit: AuditHandle) -> SecretsBundle:
    """E27-T02: M2 with the M10 Postgres credential/KCV store on the real backend.

    `storage_backend != "real"` (the fake backend: dev/CI) wires M2 with **no** credential
    store: every credential operation fails closed (`kek_unavailable`). Outside live the module
    reports STOPPED (nothing deployed, not a red alarm); in live it latches the read-only gate
    with reason `no_credential_store` at start (trading off). Tested in
    `tests/unit/credentials_m2/test_degraded_wiring.py`."""
    if settings.storage_backend != "real":
        return build_secrets_service(audit=audit)
    store = SqlAlchemyCredentialStore(
        SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "secrets")
    )
    return build_secrets_service(store, store, audit)


def _record_factory(model: Any) -> Callable[..., Any]:
    return lambda **fields: model.model_validate(fields)


def build_app_context(
    settings: Settings | None = None,
    *,
    auth_clock: Callable[[], datetime] | None = None,
    secrets_bundle: SecretsBundle | None = None,
) -> AppContext:
    """Construct an `AppContext` with real scaffold modules, no I/O performed.

    Every field is a live instance of its module's scaffold `service.py` —
    constructing them does no network/DB work (each `__init__` only sets
    `_started = False`), which is what keeps `create_app()` fast and
    fake-only per the acceptance criteria.
    """
    resolved = settings or get_settings()
    read_only_gate = ReadOnlyGate()
    mesh_self_check = MeshSelfCheckScheduler(
        check=BindingSelfCheck(
            address_enumerator=real_socket_enumerator(),
            allow_list=CidrAllowList(list(resolved.mesh_cidrs)),
        ),
        read_only_gate=read_only_gate,
        gauge=net_binding_safe,
        interval_s=resolved.mesh_self_check_interval_s,
    )
    bus_service = BusService()
    mesh_system_topic_publisher = register_system_topic_subscriber(
        bus=bus_service.bus,
        env=resolved.environment.value,
        read_only_gate=read_only_gate,
    )
    audit = _build_audit(resolved)
    secrets = secrets_bundle or _build_secrets(resolved, audit)
    return AppContext(
        settings=resolved,
        metrics=CollectorRegistry(),
        secrets=secrets.lifecycle,
        exchange_base=ExchangeBaseService(),
        exchange_bybit=ExchangeBybitService(credentials=secrets.exchange_borrower),
        bus=bus_service,
        ingestion=IngestionService(),
        book=BookService(),
        bars=BarsService(),
        orderflow=OrderflowService(),
        storage=StorageService(backend=resolved.storage_backend),
        recorder=RecorderService(),
        replay=ReplayService(),
        accounts=AccountsService(),
        oms=OmsService(),
        rules=RulesService(),
        paper=PaperService(),
        risk=RiskService(),
        auth=build_auth_service(resolved, clock=auth_clock),
        audit=audit,
        journal=JournalService(),
        admin=AdminService(secrets=secrets.metadata),
        alerts=AlertsService(),
        observability=ObservabilityService(),
        ws=WsService(),
        oms_read_only_gate=read_only_gate,
        mesh_self_check=mesh_self_check,
        mesh_system_topic_publisher=mesh_system_topic_publisher,
    )


# Start order per Sec.6.2: storage -> auth -> admin/key vault -> bus ->
# ingestion -> book -> bars -> order-flow -> recorder -> OMS -> paper ->
# rules -> replay -> gateway. `secrets`/`exchange_base`/`exchange_bybit`/
# `accounts`/`risk`/`audit`/`journal`/`alerts`/`observability` are not named
# explicitly in that sentence; they are placed at the earliest point their
# CONSTITUTION.md C-3.1 dependency edges allow, immediately before their
# first dependant.
_SUPERVISOR_ORDER: tuple[str, ...] = (
    "storage",
    "audit",  # E27-T02: before secrets so KEK load/failure is audited; M19 needs only M1/M10
    "secrets",
    "auth",
    "admin",
    "bus",
    "exchange_base",
    "exchange_bybit",
    "ingestion",
    "book",
    "bars",
    "orderflow",
    "recorder",
    "accounts",
    "risk",
    "oms",
    "paper",
    "rules",
    "alerts",
    "journal",
    "replay",
    "observability",
    "ws",
)


class Supervisor:
    """Starts modules in dependency order, stops them in reverse (Sec.6.2)."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    async def start_all(self) -> None:
        """Start in order; if one module raises, stop the already-started ones in reverse
        (E27-T02: a fatal KEK rule must not leave the audit writer / pools running)."""
        started: list[str] = []
        try:
            for name in _SUPERVISOR_ORDER:
                await getattr(self._ctx, name).start(self._ctx)
                started.append(name)
        except BaseException:
            await self._stop_each(reversed(started), 1.0)
            raise

    async def stop_all(self, grace_s: float = 15.0) -> None:
        await self._stop_each(reversed(_SUPERVISOR_ORDER), grace_s)

    async def _stop_each(self, names: Iterable[str], grace_s: float) -> None:
        """Stop every module, isolated and bounded: one raising or hanging `stop()` never
        prevents a later one (e.g. `secrets.stop()` zeroing the KEK) from running."""
        for name in names:
            try:
                async with asyncio.timeout(grace_s + 1.0):
                    await getattr(self._ctx, name).stop(grace_s)
            except Exception:  # incl. TimeoutError; CancelledError still propagates
                structlog.get_logger("candleviewer.app").exception(
                    "supervisor: module stop failed", module=name
                )


def _hub_publisher(hub: RevocationHub) -> Callable[[str, str], Awaitable[None]]:
    async def _publish(session_id: str, reason: str) -> None:
        await hub.revoke(session_id, reason)

    return _publish


@lru_cache(maxsize=1)
def _cached_spec() -> dict[str, Any]:
    """The 500 KB contract parse costs ~2 s; parse once per process."""
    return load_openapi_spec()


async def _deny_all_snapshot(user_id: uuid.UUID) -> PrincipalSnapshot:
    """Fail closed until the session/identity store (E09-S03) resolves real snapshots."""
    return PrincipalSnapshot(user_id, frozenset(), frozenset())


def _now_ms() -> int:
    return int(time.time() * 1000)


def _session_authenticator(ctx: AppContext) -> Authenticate:
    """Opaque bearer token -> (session_id, user_id, token expiry) via the session
    service. The expiry is the first instant the service refuses the token on
    time grounds; the gateway ends the socket's identity there (#2259). Raises
    (fail closed) while no session repository is wired."""

    async def _authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
        record = await ctx.auth.sessions.authenticate_access_token(token)
        return str(record.id), record.user_id, access_token_expires_at(record)

    return _authenticate


SnapshotLoader = Callable[[uuid.UUID], Awaitable[PrincipalSnapshot]]


async def gateway_overloaded_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Map a refused statechart inbox to RFC 7807 HTTP 503 (E50-T15, CV-C33)."""
    return JSONResponse(
        status_code=GatewayOverloadedError.status_code,
        content={
            "type": "about:blank",
            "title": "Service Unavailable",
            "status": GatewayOverloadedError.status_code,
            "detail": str(exc),
        },
        headers={"Retry-After": "1"},
        media_type="application/problem+json",
    )


class _NoPositionStore:
    """Open-position provider for the reset preview while no position store
    exists on main (`oms/` is a scaffold; `positions` lands with
    `0006_trading_core`). Reports the state as unknown - never 0 - so the
    preview says so and the reset demands `acknowledge_unknown_positions`.
    Replace with the OMS read model when it lands."""

    source = "not_deployed"

    async def open_position_count(self, user_id: str) -> int | None:
        return None


class _OnboardingMetrics:
    """Adapts the metrics facade to the router's `inc(name, **labels)` port."""

    _SPECS: ClassVar[dict[str, tuple[str, ...]]] = {
        "onboarding_checklist_views_total": (),
        "onboarding_step_state_total": ("step", "state"),
        "onboarding_checklist_dismissed_total": (),
        "onboarding_probe_timeouts_total": ("step",),
    }
    _BUCKETS: ClassVar[tuple[float, ...]] = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0)

    def __init__(self, metrics: Metrics) -> None:
        self._m = {
            n: metrics.counter(n, f"E09-S06 {n}", labels) for n, labels in self._SPECS.items()
        }

        self._latency = metrics.histogram(
            "onboarding_checklist_duration_seconds",
            "E09-S06 checklist assembly latency",
            (),
            buckets=self._BUCKETS,
        )

    def observe_latency(self, seconds: float) -> None:
        self._latency.child().observe(seconds)

    def inc(self, name: str, **labels: str) -> None:
        metric = self._m[name]
        child = metric.labels(*labels.values()) if labels else metric.child()
        child.inc()


def _build_onboarding_router(
    settings: Settings,
    ctx: Any,
    principal_resolver: Any,
    metrics: _OnboardingMetrics,
    store_override: Any = None,
) -> Any:
    store = store_override
    probes: dict[str, Any] = {}
    if store is None and settings.storage_backend == "real":
        store = SqlAlchemyOnboardingStore(
            SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "onboarding")
        )
    if store is not None:

        async def tailscale(_u: Any) -> StepResult:
            # Run the E09-T04 binding self-check itself (read-only; no gate mutation).
            result = await asyncio.to_thread(ctx.mesh_self_check.check.run)
            if not result.safe:
                return StepResult("blocked", "The mesh-only network check is failing.")
            return StepResult("ok")

        async def totp(u: Any) -> StepResult:
            if await store.has_confirmed_totp(u):
                return StepResult("ok")
            return StepResult("pending", "Enrol an authenticator app.")

        async def sub_account(u: Any) -> StepResult:
            if await store.has_account_binding(u):
                return StepResult("ok")
            return StepResult("pending", "No sub-account is bound to you yet.")

        async def api_key(u: Any) -> StepResult:
            # Real probe: The exchange blocks key creation for 48 h after the sub-account
            # binding (US-ONB-007). Key inventory itself ships with E27.
            bound_at = await store.latest_binding_at(u)
            if bound_at is None:
                return StepResult("pending", "Bind a sub-account first.")
            # NOTE: exchange_accounts (E27) does not exist yet; binding time is the only
            # available proxy for account creation. Swap when E27 lands.
            restricted = bybit_key_restriction(bound_at, datetime.now(UTC))
            if restricted is not None:
                return restricted
            # Key inventory (E27) has not shipped: stay pending, never satisfied.
            return StepResult("pending", "API-key inventory is coming soon.")

        probes = {
            "tailscale": tailscale,
            "totp": totp,
            "sub_account": sub_account,
            "api_key": api_key,
        }

    # Steps whose owning epics (E39 limits, E27 demo sessions) have not shipped have
    # no probe and are switched off in the flag table: they render `pending`
    # ("coming soon") and keep the card incomplete/undismissable until they ship.
    flags: dict[str, bool] = {"profile_limits": False, "demo_session": False}
    return make_onboarding_router(
        store, principal_resolver, probes, flags, metrics, _LazyAuditEmitter(ctx.audit)
    )


class _RuleCompileTelemetry:
    """E35-T04: compile counters + a high-severity telemetry event on form/graph divergence."""

    def __init__(self, metrics: Metrics) -> None:
        self._compiles = metrics.counter(
            "rule_compile_total", "E35-T04 rule compiles", ("kind", "result")
        )
        self._diverged = metrics.counter(
            "rule_roundtrip_divergence_total", "E35-T04 form/graph divergences (high severity)",
            ("kind",),
        )  # fmt: skip

    def on_compile(self, editor: str, result: str) -> None:
        self._compiles.labels(editor, result).inc()

    def on_divergence(self, editor: str, n_diffs: int) -> None:
        self._diverged.labels(editor).inc()
        structlog.get_logger("candleviewer.rules").error(
            "rule_roundtrip_divergence", editor=editor, diffs=n_diffs, severity="high"
        )


def create_app(
    settings: Settings | None = None,
    *,
    snapshot_loader: SnapshotLoader | None = None,
    user_role_store: UserRoleStore | None = None,
    principal_resolver: SnapshotResolver | None = None,
    ws_authenticate: Authenticate | None = None,
    auth_clock: Callable[[], datetime] | None = None,
    onboarding_store: Any = None,
    bars_now_us: Callable[[], int] | None = None,
    secrets_bundle: SecretsBundle | None = None,
) -> FastAPI:
    """Build the FastAPI application without touching Postgres/QuestDB/network.

    Per E02-T05 acceptance criterion 3: constructing the app with fakes-only
    settings must not perform I/O, and `GET /healthz` must return 200 with a
    build-info body. The module supervisor is *not* started here — that is
    driven by the ASGI lifespan in `services/api/main.py` (or a test's own
    fixture), keeping `create_app()` itself synchronous and side-effect-free.

    E09-T04: `MeshOnlyMiddleware` is mounted here (not in the lifespan) so it
    protects every request, including ones that arrive before the lifespan's
    boot self-check has finished — a request is checked against the mesh
    CIDR allow-list before authentication regardless of process readiness.
    The audit sink stays the `NullAuditSink` default until the real M19
    `audit` module implements a concrete `emit()` (tracked by that module's
    own ticket); wiring a real sink here is a one-line change once it lands.
    """
    resolved = settings or get_settings()
    spec = _cached_spec()
    app = FastAPI(
        title="CandleViewer API",
        version=resolved.version,
        dependencies=[Depends(make_deny_undeclared_dependency(declared_operations(spec)))],
    )
    app.add_exception_handler(GatewayOverloadedError, gateway_overloaded_handler)
    install_error_redaction(app)  # E43-T06: no secret echo via 422/500 bodies
    ctx = build_app_context(resolved, auth_clock=auth_clock, secrets_bundle=secrets_bundle)
    app.state.app_context = ctx
    # #2060: klines hot/cold boundary from the DB-seeded retention policy; the lifespan loads it
    # (`load_kline_policy`), until then (and on failure) the 90 d fallback applies.
    kline_boundary = KlineHotBoundary()
    app.state.kline_boundary = kline_boundary
    _kb_pg = (
        SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "kline-boundary")
        if resolved.storage_backend == "real"
        else None
    )
    app.state.kline_boundary_pg = _kb_pg
    # E16-T04: sessions-backed coverage + `recording_started_at` (real backend only; the fake
    # backend keeps the tape-based provider, and the coverage route answers 503).
    coverage_service = (
        CoverageService(
            SqlAlchemyRecorderRepository(_kb_pg),
            now_us=lambda: time.time_ns() // 1000,
            # E16-T05 roll-off watermarks: older -> parquet, newer -> questdb.
            watermarks=FileWatermarkStore(DatasetRegistry(resolved.parquet_root)),
            # E16-T10: imported archive windows -> `trades` coverage labelled `archive`.
            archive=FileImportLedger(DatasetRegistry(resolved.parquet_root)),
        )
        if _kb_pg is not None
        else None
    )
    app.state.coverage_service = coverage_service
    if coverage_service is not None:
        ctx.recorder.attach_coverage(coverage_service)
    app.state.kline_boundary_refresh = KlineBoundaryRefreshTask(
        kline_boundary,
        kline_policy_loader(SqlAlchemyRecorderRepository(_kb_pg) if _kb_pg is not None else None),
        float(resolved.kline_boundary_refresh_s),
    )
    if resolved.ingestion_ws_enabled:
        wire_public_ws(ctx, kline_boundary)
    # E12 #2031 (flag `bars_enabled`, default off - C-4.13; removal with #398/#399): the set
    # and its writer are started/stopped by the lifespan (set first, then writer).
    bars_reader: BarReader | None = None
    if resolved.bars_enabled:
        bars_sink = _build_bars_sink(resolved)
        app.state.bars_runtime = wire_bars(
            ctx,
            inner_sink=bars_sink,
            sink_stop=bars_sink.stop if bars_sink is not None else None,
            sink_degraded=(lambda: bars_sink.pgwire.degraded) if bars_sink is not None else None,
            now_us=bars_now_us or (lambda: time.time_ns() // 1000),
            tick_size=lambda sym: _catalogue_tick_size(ctx, sym),
        )
        if bars_sink is not None:
            bars_reader = BarReader(bars_sink.pgwire, _no_rebuild_executor)
        if bars_reader is not None and ctx.ingestion.klines is not None:
            # E12-T05: `/market/klines` tier (1) — tape-built `bars_time` wins over klines.
            ctx.ingestion.klines.attach_tape(
                tape_time_bar_reader(bars_reader, timeout_s=QUERY_TIMEOUT_S)
            )
    # E07-X02 (SR-094): supervised weekly scrub; started/stopped by the lifespan.
    app.state.scrub_task = (
        ScrubTask(
            DatasetRegistry(resolved.parquet_root),
            LoggingSystemEventSink(),
            interval_s=float(resolved.scrub_interval_s),
        )
        if resolved.scrub_enabled
        else None
    )
    # E35-T02: unmatched rule-run retention prune; started by the lifespan only
    # when `retention_enabled` (RetentionSchedule.rule_jobs()).
    app.state.rule_prune_task = RulePruneTask(
        SqlAlchemyRulesRepository(
            SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "rules")
        ),
        RetentionSchedule.from_settings(resolved),
    )
    identity = build_identity_provider(resolved)
    app.state.identity_provider = identity
    overrides = LogLevelOverrides()
    app.state.log_level_overrides = overrides
    # `principal_resolver=None` -> fails closed with 501 until E09-S03 (as /admin/audit).
    app.include_router(make_log_level_router(overrides, _LazyAuditEmitter(ctx.audit)))
    app.include_router(
        make_health_router(
            resolved,
            ctx.metrics,
            mesh_read_only_gate=ctx.oms_read_only_gate,
            write_behind=lambda: _write_behind_buffers(ctx),
            ingestion_health=ctx.ingestion.health,
            secrets_health=ctx.secrets.health,
        )
    )
    # E04-T04: cached component health. Unbuilt modules register `not_deployed`
    # probes; the ticker is started/stopped by the lifespan (`app.state`).
    health_pg = (
        SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "health")
        if resolved.storage_backend == "real"
        else None
    )
    app.state.health_pg = health_pg
    health_registry = HealthRegistry(
        events=PgSystemEventWriter(health_pg) if health_pg is not None else None,
        on_snapshot=HealthSystemPublisher(ctx.bus.bus, resolved.environment.value),
    )
    health_registry.register_placeholders()
    if health_pg is not None:
        q_host, _, q_port = resolved.questdb_pg.partition(":")
        register_real_probes(
            health_registry,
            pg_repo=health_pg,
            questdb_host=q_host,
            questdb_port=int(q_port or 8812),
            parquet_root=resolved.parquet_root,
            disk_path=resolved.parquet_root,
        )
    bind_health_metrics(health_registry, ctx.metrics, resolved)
    register_write_behind_probe(health_registry, lambda: _write_behind_buffers(ctx))
    register_ingestion_probe(health_registry, ctx.ingestion.health)
    register_secrets_probe(health_registry, ctx.secrets.health)
    register_bars_probe(health_registry, ctx.bars.health)
    register_bars_writer_probe(
        health_registry, lambda: _bars_writer_state(getattr(app.state, "bars_runtime", None))
    )
    register_public_ws_probe(health_registry, lambda: ctx.ingestion.ws)
    app.state.health_registry = health_registry
    app.include_router(
        make_health_report_router(
            health_registry,
            version=resolved.version,
            git_sha=resolved.git_sha,
            environment=resolved.environment.value,
        )
    )
    csrf_codec = build_csrf_codec(resolved)
    app.state.csrf_codec = csrf_codec
    # In-flight CSRF-refusal audits; drained (bounded) at shutdown before audit stops.
    csrf_audits = RefusalAuditTracker()
    app.state.csrf_refusal_audits = csrf_audits
    app.include_router(make_auth_router(ctx.auth, ctx.audit, identity=identity, csrf=csrf_codec))
    # E09-S03: session routes; revocation is pushed to sockets via the hub
    # (4401). Identity provider is E09-T03, so refresh/session return 501 and
    # every route answers 503 until a session repository is wired.
    revocation_hub = RevocationHub()
    app.state.revocation_hub = revocation_hub
    app.include_router(
        make_session_router(
            ctx.auth,
            ctx.audit,
            identity=identity,
            publish_revocation=_hub_publisher(revocation_hub),
            allowed_origins=resolved.allowed_origin_set,
            csrf=csrf_codec,
            audit_tracker=csrf_audits,  # one in-flight cap + shutdown drain for refusal audits
        )
    )
    # QA #1648 d1: live WS gateway. Role changes (`PUT /users/{id}/roles`)
    # notify the registry, which pushes `permission_change` and revokes
    # now-forbidden subscriptions. Snapshots fail closed (no permissions)
    # until the identity store is injected.
    # #377 wiring: E08 upstream sink, BarBuilderSet leases, audit, instrument check, snapshots
    # (pending stubs until #2195-#2197), sequencing; lifecycle + shutdown in `WsRuntime`.
    ws_upstream = UpstreamRefs(IngestionUpstreamSink(ingestion_streams(ctx)))
    ws_services = SubscriptionServices(
        upstream=ws_upstream,
        bars=getattr(getattr(app.state, "bars_runtime", None), "builder_set", None),
        audit=_LazyAuditEmitter(ctx.audit),
        instrument_known=lambda sym: _ws_symbol_known(ctx, sym),
        snapshots=default_snapshot_router(),
        sequencing=SequencingHub(),
    )
    ws_registry = ConnectionRegistry(
        snapshot_loader or _deny_all_snapshot, _now_ms, services=ws_services
    )
    ws_hub = GatewayHub(max_per_user=resolved.ws_max_connections_per_user)
    kill_switch = KillSwitchView()
    app.state.ws_registry = ws_registry
    app.state.ws_hub = ws_hub
    app.state.ws_events = WsEvents(ws_registry, ws_hub, kill_switch)
    app.state.ws_runtime = WsRuntime(ws_hub, ws_upstream, resolved)
    app.include_router(
        make_ws_router(
            authenticate=ws_authenticate or _session_authenticator(ctx),
            registry=ws_registry,
            revocation_hub=revocation_hub,
            allowed_origins=resolved.allowed_origin_set,  # SR-042/SR-183 upgrade check (#2239)
            hub=ws_hub,
            audit=_LazyAuditEmitter(ctx.audit),
            auth_timeout_s=resolved.ws_auth_timeout_s,
            max_frame_bytes=resolved.ws_max_inbound_frame_bytes,
            server_version=resolved.version,
            git_sha=resolved.git_sha,
            kill_switch=kill_switch.snapshot,
            system_notices=lambda: _gate_notices(ctx),
        )
    )
    # E27-T02: gate transitions (KEK latch, mesh trip) reach connected clients directly.
    ctx.mesh_system_topic_publisher.direct_sinks.append(ws_hub.broadcast_system)
    # E09-S04: step-up, owner TOTP reset and the read-only write guard.
    app.include_router(
        make_step_up_router(
            ctx.auth,
            _LazyAuditEmitter(ctx.audit),
            principal_resolver=principal_resolver,
            positions=_NoPositionStore(),
            users=user_role_store,
        )
    )
    # B16 audit actions write through the M19 emitter (PR #1674 finding 3).
    set_b16_audit_sink(_LazyAuditEmitter(ctx.audit))
    app.middleware("http")(make_read_only_guard(ctx.auth, _LazyAuditEmitter(ctx.audit)))
    # Audit emitter + notifier are mandatory; store/resolver `None` -> 501.
    app.include_router(
        make_users_router(
            user_role_store,
            _LazyAuditEmitter(ctx.audit),
            principal_resolver,
            ws_registry,
            auth=ctx.auth,
        )
    )
    app.include_router(
        make_invites_router(ctx.auth, _LazyAuditEmitter(ctx.audit), principal_resolver)
    )
    # QA #1596: real session-backed resolver; without an identity provider
    # (fake backend) it stays `None` and every call fails closed with 501.
    audit_resolver = (
        SessionAuditPrincipalResolver(lambda: ctx.auth.sessions, identity)
        if identity is not None
        else None
    )
    audit_budget = AuditRecordBudget(
        per_hour=resolved.audit_record_budget_per_hour,
        owner_per_hour=resolved.audit_record_budget_owner_per_hour,
        tracked_users=resolved.audit_budget_tracked_users,
        inflight_cap=resolved.audit_inflight_writes,
        flush_pages=resolved.audit_read_flush_pages,
        flush_seconds=resolved.audit_read_flush_seconds,
    )
    # Flush cadence and shutdown drain for the budget's counts; the lifespan runs it.
    app.state.audit_budget_flush = AuditBudgetFlushTask(audit_budget, _LazyAuditEmitter(ctx.audit))
    app.include_router(
        make_audit_router(
            ctx.audit,
            audit_resolver,
            limiter=AuditQueryLimiter(
                rate_per_minute=resolved.audit_query_rate_per_minute,
                max_concurrent=resolved.audit_query_max_concurrent,
                tracked_users=resolved.audit_budget_tracked_users,
            ),
            budget=audit_budget,
            query_timeout_ms=resolved.audit_query_timeout_ms,
        )
    )
    app.include_router(make_hotkey_audit_router(_LazyAuditEmitter(ctx.audit), audit_resolver))
    # E04-T06: frontend telemetry push. One facade per process on ctx.metrics
    # (the lifespan's MetricsRuntime reuses it). Session-authenticated via the
    # same session resolver; `None` (fake backend) fails closed with 501.
    # Process collectors read /proc; the lifespan adds them (no I/O here).
    metrics_facade = Metrics(resolved.environment.value, registry=ctx.metrics)
    app.state.metrics_facade = metrics_facade
    # E08-T06: serve the declared ingestion/adapter series on the scraped
    # registry with consistent `env` + `exchange` labels (the venue name is
    # owned by the adapter, C-2.2).
    app.state.ingestion_metrics = export_ingestion_metrics(
        ctx.metrics, env=resolved.environment.value, exchange=ctx.exchange_bybit.venue
    )
    # E12-T03: bars series (builders + BarBuilderSet) on the scraped registry.
    app.state.bars_metrics = export_bars_metrics(ctx.metrics, env=resolved.environment.value)
    app.state.secrets_metrics = export_secrets_metrics(ctx.metrics, env=resolved.environment.value)
    # E17-T02: CVWB encode frames/bytes per body_kind.
    app.state.cvwb_metrics = export_cvwb_metrics(ctx.metrics, env=resolved.environment.value)
    # #377: every `cv_ws_*` gateway series (lifecycle, subscriptions, sequencing).
    app.state.ws_metrics = export_ws_metrics(ctx.metrics, env=resolved.environment.value)
    # #2090: auth series (incl. auth_csrf_refused_total) on the scraped registry.
    app.state.auth_metrics = export_auth_metrics(ctx.metrics, env=resolved.environment.value)
    # E40-T01: alert_deliveries retention purge + alert gauges (lifespan-started).
    _alert_pg = SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "alerts")
    _retention = RetentionSchedule.from_settings(resolved)
    # The purge needs the cv_owner role (trg_ad_append); the app-role DSN can't DELETE.
    _owner_dsn = resolved.pg_owner_dsn
    app.state.alert_purge_task = AlertDeliveriesPurgeTask(
        SqlAlchemyAlertDeliveryRepository(
            SqlAlchemyRelationalRepository(_owner_dsn.get_secret_value(), "alerts-retention")
            if _owner_dsn is not None
            else _alert_pg
        ),
        _retention,
        archive_root=Path(resolved.parquet_root),
        has_owner_dsn=_owner_dsn is not None,
    )
    app.state.alert_gauge_task = AlertGaugeTask(
        SqlAlchemyAlertRepository(_alert_pg),
        metrics_facade.gauge(
            "cv_alerts_total",
            "Non-deleted alerts by enabled flag.",
            ("state",),
            max_series=2,
        ),
        metrics_facade.gauge("cv_alert_deliveries_pending", "Queued alert deliveries."),
        enabled=_retention.enabled,
    )
    # E09-S06: server-evaluated first-run checklist. Steps whose owning epic
    # has not shipped (E27 api_key/demo, E39 profile limits) have no probe and
    # render `pending` ("coming soon") via the flag table, never a client stub.
    app.include_router(
        _build_onboarding_router(
            resolved,
            ctx,
            principal_resolver,
            _OnboardingMetrics(metrics_facade),
            onboarding_store,
        )
    )
    # E04-T06: per-stage tick latency on the real ingestion publish path.
    # Offset = ClockGuard's measured exchange-local offset (E08 wires it via
    # `ctx.ingestion.clock_offset_ms`); the synthetic feed reports 0.
    register_r0(metrics_facade)  # idempotent; the lifespan reuses this facade
    ctx.ingestion.attach_latency(
        StageRecorder(metrics_facade.get("ingest_stage_seconds"), resolved.telemetry_sample_n)
    )
    app.include_router(
        make_telemetry_router(
            TelemetrySink(metrics_facade),
            SessionRateLimiter(time.monotonic),
            SessionKeyResolver(audit_resolver) if audit_resolver is not None else None,
            enabled=resolved.telemetry_enabled,
        )
    )
    # E04-S02: support bundle. Real collectors (log ring, /metrics registry,
    # health snapshot, system_events); RBAC via the session resolver, `None`
    # (fake backend) fails closed with 501.
    support_bundle = build_support_bundle_service(
        registry=ctx.metrics,
        metrics=metrics_facade,
        health=health_registry,
        events_query=PgSystemEventReader(health_pg) if health_pg is not None else None,
        config=filter_config(os.environ),
        build_info={
            "version": resolved.version,
            "git_sha": resolved.git_sha,
            "environment": resolved.environment.value,
        },
        out_dir=Path(resolved.parquet_root).parent / "support_bundles",
    )
    app.state.support_bundle = support_bundle
    app.include_router(
        make_support_bundle_router(support_bundle, _LazyAuditEmitter(ctx.audit), audit_resolver)
    )
    # E16-T05: weekly cold-tier compaction on demand (async job, polled via /admin/jobs).
    _cold_registry = DatasetRegistry(resolved.parquet_root)

    async def _compact(
        symbols: list[str] | None, older_than_days: int | None, progress: Callable[[float], None]
    ) -> dict[str, object]:
        summary = await compact_all(
            _cold_registry,
            Compactor(events=LoggingSystemEventSink()),
            symbols=symbols,
            older_than_days=older_than_days,
            on_progress=progress,
        )
        return summary.as_result()

    admin_jobs = AdminJobStore()
    app.state.admin_jobs = admin_jobs  # cancelled by the lifespan at shutdown
    app.include_router(
        make_recorder_admin_router(
            admin_jobs,
            _compact,
            _LazyAuditEmitter(ctx.audit),
            audit_resolver,
            # E16-T10: archive import (503 unless the real backend + coverage are composed).
            import_runner=build_import_runner(
                ctx.exchange_bybit.trade_archive(
                    max_concurrency=resolved.import_max_concurrency,
                    max_mbps=resolved.import_max_mbps,
                    max_uncompressed_mb=resolved.import_max_uncompressed_mb,
                    base_url=resolved.bybit_archive_base,
                ),
                resolved.parquet_root,
                coverage_service,
                backlog_rows=current_write_backlog_rows,
            ),
        )
    )
    # E16-T05: nightly roll-off composition (constructed only; scheduling is flag-gated).
    app.state.rolloff_job = build_rolloff_job(
        resolved,
        _LazyAuditEmitter(ctx.audit),
        SqlAlchemyRecorderRepository(_kb_pg) if _kb_pg is not None else None,
    )
    # QA defect #1622 blocker: `/market/klines` (E08-S06 core deliverable)
    # was missing entirely — cache-only reads today (`ctx.storage.
    # market_data`); backfilling from the exchange itself is wired once
    # E08-T02 lands a real exchange adapter (see `api/market.py`
    # module docstring). `principal_resolver` stays `None` for the same
    # reason as `make_audit_router` above (no session-verification module
    # wired yet) — every request fails closed with `501`, not with a silent
    # unauthenticated read (C-12.4, PR #1626 review finding: this route was
    # previously reachable by any mesh caller with no RBAC check at all).
    app.include_router(
        make_market_router(
            lambda: ctx.storage.market_data,
            read_service_provider=lambda: ctx.ingestion.klines,
            # SR-E12-08: only catalogue-listed, trading symbols may start a backfill.
            symbol_listed=lambda sym: _catalogue_listed(ctx, sym),
        )
    )
    # E12-T05: `/market/bars` over `bars_*` (503 until a real QuestDB reader is composed).
    app.include_router(
        make_market_bars_router(
            lambda: bars_reader,
            recording_started_at_us=recording_started_at_us(ctx),
            principal_resolver=audit_resolver,
            symbol_listed=lambda sym: _catalogue_listed(ctx, sym),
            now_us=lambda: time.time_ns() // 1000,
        )
    )
    # E16-T04: `/market/data-coverage` (503 until a CoverageService is composed).
    app.include_router(
        make_data_coverage_router(
            lambda: coverage_service,
            principal_resolver=audit_resolver,
            symbol_listed=lambda sym: _catalogue_listed(ctx, sym),
        )
    )
    # E08-S01-2: served from the scheduler's in-memory snapshot; `503` until
    # `wire_instrument_catalogue()` attaches one (needs a real Postgres +
    # exchange REST client). Resolver `None` -> fail-closed `501` (see above).
    app.include_router(make_instruments_router(lambda: ctx.ingestion.instruments))
    # E08-S03: merged ticker snapshot; session-backed resolver (501 only without identity).
    app.include_router(
        make_ticker_router(lambda: ctx.ingestion.tickers, principal_resolver=audit_resolver)
    )
    # E24-T02: funding history + predicted rate; same resolver/fail-closed rules.
    app.include_router(
        make_funding_router(lambda: ctx.orderflow.funding, principal_resolver=audit_resolver)
    )
    # E24-T02-F1: compose FundingService (503 until the hot tier serves it).
    app.state.funding_refresh_task = _compose_funding(ctx, resolved)
    # E08-S04: in-memory hot tape (newest-first); same resolver/fail-closed rules.
    app.include_router(
        make_trades_router(lambda: ctx.ingestion.trades, principal_resolver=audit_resolver)
    )
    # E35-T03: rule vocabulary + IR schema (fail-closed 501 without a resolver).
    rule_telemetry = _RuleCompileTelemetry(metrics_facade)
    # E35-S04: scope enforcement is backed by user_account_access (real backend only);
    # on the fake backend there is no resolver, so scoped/live rules fail closed (501).
    if resolved.storage_backend == "real":
        ctx.rules.wire_scope(
            SqlAlchemyScopeSource(
                SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "rule_scope")
            ),
            resolved.environment.value,
            audit_writer_sink(_LazyAuditEmitter(ctx.audit)),
        )
    app.include_router(
        make_rules_router(
            lambda: ctx.rules.registry(),
            principal_resolver=audit_resolver,
            recorded_symbols=lambda: ctx.recorder.recorded_symbols(),
            on_compile=rule_telemetry.on_compile,
            on_divergence=rule_telemetry.on_divergence,
            scope_resolver=ctx.rules.scope_resolver,
            scope_refresh=ctx.rules.refresh_scope,
        )
    )
    # E35-S01: rule store / versions / active-version / mode routes (fail-closed 501
    # without an identity provider). Audit (C-2.9) is write-ahead via the M19 emitter and
    # state changes are published on the `{env}.rules` bus topic that the WS gateway fans out.
    _rules_audit = make_rules_audit(_LazyAuditEmitter(ctx.audit))

    async def _rules_broadcast(payload: dict[str, Any]) -> None:
        await ctx.bus.bus.publish(
            Topic(env=resolved.environment.value, domain="rules"),
            {k: v for k, v in payload.items() if k != "topic"},
        )

    ctx.rules.bind(
        store=PostgresRuleStore(
            SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "rules")
        ),
        audit=_rules_audit,
        broadcast=_rules_broadcast,
    )
    rules_actor = (
        SessionRulesActorResolver(lambda: ctx.auth.sessions, lambda: ctx.auth.step_up, identity)
        if identity is not None
        else None
    )
    app.include_router(
        make_rules_crud_router(
            lambda: ctx.rules.manager(),
            rules_actor.resolve if rules_actor else None,
            scope_resolver=lambda: ctx.rules.scope_resolver,
            scope_refresh=ctx.rules.refresh_scope,
        )
    )
    # E40-T02: notify-only alert CRUD. Same session->Actor resolver as /rules (fail-closed 501
    # without an identity provider); write-ahead audit via the M19 emitter (C-2.9).
    _alert_rejects = metrics_facade.counter(
        "cv_alert_compile_rejected_total", "Alert compiles refused, by reason.", ("reason",),
        max_series=8,
    )  # fmt: skip
    _alert_compile = metrics_facade.histogram(
        "cv_alert_compile_seconds", "Alert compile + validate time.",
        buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.3, 1.0),
    )  # fmt: skip

    def _on_alert_compile(seconds: float, reason: str | None) -> None:
        _alert_compile.child().observe(seconds)
        if reason is not None:
            _alert_rejects.labels(reason).inc()

    app.include_router(
        make_alerts_router(
            lambda: SqlAlchemyAlertRepository(_alert_pg),
            lambda: ctx.rules.registry(),
            rules_actor.resolve if rules_actor else None,
            _LazyAuditEmitter(ctx.audit),
            on_compile=_on_alert_compile,
            on_change=ctx.alerts.on_alert_changed,
        )
    )
    if resolved.alerts_webhook_enabled:  # refused whatever the evaluator flag (E40-S03)
        default_adapters(None, webhook_enabled=True)  # raises
    if resolved.alerts_evaluator_enabled:
        ctx.alerts.bind(
            _alert_evaluator_factory(ctx, _alert_pg, metrics_facade),
            _alert_dispatcher(_alert_pg, metrics_facade, resolved.alerts_webhook_enabled),
        )
    # E08-S05: maintained L2 book snapshot (503 while resyncing, never a patched book).
    app.include_router(
        make_orderbook_router(lambda: ctx.ingestion.books, principal_resolver=audit_resolver)
    )
    # Middleware order, outermost first (Starlette: last added = outermost):
    #   Correlation -> MeshOnly -> Csrf -> read-only/step-up guard -> routes.
    # #2090 (SR-041/SR-042): CSRF runs inside MeshOnly, so off-mesh traffic never
    # reaches a session lookup or an audit write, and outside every route-level
    # guard (read-only/step-up, RBAC): no write reaches them without a valid token.
    app.add_middleware(
        CsrfMiddleware,
        codec=csrf_codec,
        sessions=lambda: ctx.auth.sessions if ctx.auth.sessions_is_active else None,
        audit=_LazyAuditEmitter(ctx.audit),
        allowed_origins=resolved.allowed_origin_set,
        operations=frozenset(declared_operations(spec)),
        clock=auth_clock or (lambda: datetime.now(UTC)),
        tracker=csrf_audits,
    )
    # E09-T04: rejects off-mesh requests before any credential is evaluated.
    app.add_middleware(
        MeshOnlyMiddleware,
        allow_list=CidrAllowList(list(resolved.mesh_cidrs)),
        trusted_proxy_header=resolved.mesh_trusted_proxy_header,
        trusted_proxy_address=resolved.mesh_trusted_proxy_address,
    )
    # E04-T02: outermost (added last) so every request - even a mesh rejection -
    # gets a correlation id and the X-Correlation-Id response header.
    app.add_middleware(CorrelationMiddleware)
    # E09-T03 / #1648: a served route without an RBAC declaration fails the build.
    assert_app_routes_declared(app, spec)
    return app


def _alert_dispatcher(
    pg: SqlAlchemyRelationalRepository, facade: Metrics, webhook_enabled: bool
) -> AlertDispatcher:
    """E40-T04: `alert.deliver` outbox poller. Email stays disabled (suppressed) until the
    E04 relay transport is provisioned; no network transport is constructed here."""
    adapters = default_adapters(None, webhook_enabled=webhook_enabled)  # refuses webhook=on
    m = {
        "cv_alert_delivery_total": facade.counter(
            "cv_alert_delivery_total", "Settled alert deliveries.", ("transport", "state"),
            max_series=15),
        "cv_alert_delivery_latency_seconds": facade.histogram(
            "cv_alert_delivery_latency_seconds", "Alert firing -> delivery sent.", ("transport",),
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 30.0, 300.0), max_series=5),
        "cv_alert_delivery_attempts": facade.histogram(
            "cv_alert_delivery_attempts", "Adapter attempts per settled delivery.",
            buckets=(1, 2, 3, 4, 6, 8, 10)),
        "cv_outbox_dead_total": facade.counter(
            "cv_outbox_dead_total", "Dead-lettered outbox rows.", ("topic",), max_series=8),
    }  # fmt: skip

    def _sink(name: str, labels: tuple[str, ...]) -> Any:
        b = m[name]
        return b.labels(*labels) if labels else b.child()

    return AlertDispatcher(
        SqlAlchemyAlertDispatchStore(pg),
        adapters,
        worker=f"api-{os.getpid()}-{uuid.uuid4().hex[:8]}",
        now=lambda: datetime.now(UTC),
        metric=_sink,
    )


def _alert_evaluator_factory(
    ctx: AppContext, pg: SqlAlchemyRelationalRepository, facade: Metrics
) -> Callable[[], Awaitable[AlertEvaluator | None]]:
    """E40-T03: evaluator over the rules module's pushed metric source (shared E35 bus)."""
    metric = _alert_metric_sink(facade)

    async def _make() -> AlertEvaluator | None:
        source = ctx.rules.metric_source
        if source is None:  # E35 evaluator off: no metric bus to subscribe to
            return None
        audit = _LazyAuditEmitter(ctx.audit)
        store = SqlAlchemyAlertFiringStore(
            pg, topic=TOPIC_ALERT_DELIVER, dedup_key=alert_deliver_dedup_key
        )
        return AlertEvaluator(
            store, source, charts=AlertCharts(), audit=audit, metrics=AlertMetrics(metric)
        )

    return _make


def _alert_metric_sink(facade: Metrics) -> Callable[[str, tuple[str, ...]], Any]:
    """Ticket "Observability" metrics, registered once through the facade (E04-T03)."""
    m = {
        "cv_alert_eval_latency_seconds": facade.histogram(
            "cv_alert_eval_latency_seconds", "Alert condition met -> delivery committed.",
            buckets=(0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)),
        "cv_alerts_armed": facade.gauge("cv_alerts_armed", "Armed alerts in the evaluator."),
        "cv_alert_subscriptions": facade.gauge(
            "cv_alert_subscriptions", "Distinct condition_hash subscriptions."),
        "cv_alert_fires_total": facade.counter(
            "cv_alert_fires_total", "Alert firings.", ("trigger_mode",), max_series=3),
        "cv_alert_suppressed_total": facade.counter(
            "cv_alert_suppressed_total", "Gated alert firings.", ("reason",), max_series=5),
        "cv_alert_autodisarmed_total": facade.counter(
            "cv_alert_autodisarmed_total", "Alerts auto-disarmed.", ("reason",), max_series=4),
        "cv_alert_eval_queue_depth": facade.gauge(
            "cv_alert_eval_queue_depth", "Alert evaluation queue depth."),
        "cv_alert_eval_dropped_total": facade.counter(
            "cv_alert_eval_dropped_total", "Alert ticks shed by the bounded queue."),
    }  # fmt: skip

    def _sink(name: str, labels: tuple[str, ...]) -> Any:
        b = m[name]
        return b.labels(*labels) if labels else b.child()

    return _sink


def _bars_writer_state(runtime: Any) -> tuple[bool, str] | None:
    return None if runtime is None else runtime.writer_state()


def _catalogue_listed(ctx: AppContext, symbol: str) -> bool:
    """True iff `symbol` is in the instrument catalogue snapshot and trading (fail closed when
    no catalogue is attached yet)."""
    scheduler = ctx.ingestion.instruments
    snap = scheduler.snapshot() if scheduler is not None else None
    inst = snap.get(symbol) if snap is not None else None
    return inst is not None and inst.status == "trading"


def _ws_symbol_known(ctx: AppContext, symbol: str) -> bool:
    """WS `sub` symbol check: the catalogue decides once it has a snapshot; before that only the
    topic grammar (`SYMBOL_RE`) applies, and E08 ingestion still refuses unlisted symbols."""
    scheduler = ctx.ingestion.instruments
    if scheduler is None or scheduler.snapshot() is None:
        return True
    return _catalogue_listed(ctx, symbol)


def _catalogue_tick_size(ctx: AppContext, symbol: str) -> Decimal | None:
    scheduler = ctx.ingestion.instruments
    snap = scheduler.snapshot() if scheduler is not None else None
    inst = snap.get(symbol) if snap is not None else None
    return None if inst is None else inst.tick_size


def _compose_funding(ctx: AppContext, settings: Settings) -> Any:
    """E24-T02-F1: fake backend -> in-memory store, no fetcher (no network).

    Real backend -> no store yet, so NO fetcher/refresh task is built (pages that cannot be
    written must not spend MARKET_DATA budget); `/market/funding` serves 503 until the QuestDB
    funding client lands (follow-up issue #1939, parent #1932 / #666)."""
    store: Any = None
    if settings.storage_backend == "fake":
        from candleviewer.storage.questdb.funding_store import InMemoryFundingStore

        store = InMemoryFundingStore()
    else:
        structlog.get_logger("candleviewer.funding").info(
            "funding_refresh_disabled",
            reason="pending_questdb_funding_client",
            issue="#1939",
        )
    return wire_funding(
        ctx, store=store, fetcher=None, closer=None, now_us=lambda: time.time_ns() // 1000
    )


def wire_instrument_catalogue(
    ctx: AppContext,
    *,
    fetch_instruments: InstrumentsFetcher,
    relational: SqlAlchemyRelationalRepository,
) -> InstrumentsRefreshScheduler:
    """Compose the E08-S01-2 catalogue: the exchange adapter's neutral
    instruments fetcher (M4, built by the adapter and passed in as the
    neutral `InstrumentsFetcher` port) + Postgres repository (M10) + bus
    publisher (M5) -> ingestion (M6) scheduler. Only this composition root
    sees all four modules (C-3.1)."""
    bus = ctx.bus.bus
    env = ctx.settings.environment.value

    async def _publish(event: InstrumentUpdatedEvent) -> None:
        topic = Topic(env=env, domain="instruments", symbol=event.symbol, detail="updated")
        await bus.publish(topic, event)

    scheduler = InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch_instruments,
        repository=SqlAlchemyInstrumentsRepository(relational),
        publish=_publish,
    )
    ctx.ingestion.attach_instruments(scheduler)
    return scheduler


async def _no_rebuild_executor(symbol: str, spec_hash: str, from_us: int, to_us: int) -> None:
    """Stale-`build_version` rebuilds have no executor yet (E12-T02 schedules, nothing runs
    them); logged so a stale series is visible. TODO(#2017): wire the rebuild worker."""
    structlog.get_logger("candleviewer.bars").info("bars_rebuild_unexecuted", spec_hash=spec_hash)


def _build_bars_sink(settings: Settings) -> QuestDbRowSink | None:
    """#2037: the real QuestDB ILP sink on the `real` storage backend; `None` (guarded stub +
    `bars_rows_not_persisted` warning) otherwise. Connects lazily - no I/O here."""
    if settings.storage_backend != "real":
        return None
    return QuestDbRowSink(
        settings.questdb_ilp,
        settings.questdb_pg,
        settings.questdb_pg_user,
        settings.questdb_pg_password.get_secret_value(),
    )


def _write_behind_buffers(ctx: AppContext) -> list[WriteBehindLike]:
    """#1918: the hot-tier write-behind buffers wired in this process."""
    out: list[WriteBehindLike] = []
    if ctx.ingestion.trades is not None:
        out.append(ctx.ingestion.trades.write_behind)
    if isinstance(ctx.ingestion.books, BookStream):
        out.append(ctx.ingestion.books.write_behind)
    return out


def kline_policy_loader(
    repo: SqlAlchemyRecorderRepository | None,
) -> Callable[[], Awaitable[RetentionPolicy | None]]:
    """#2060: loader of the klines hot window from the DB-seeded `retention_policies` (via the
    recorder repository). Only an EXPLICIT rule counts: no rule (or no repository, fake backend)
    -> no policy -> the 90 d fallback."""

    async def load() -> RetentionPolicy | None:
        if repo is None:
            return None
        days = await repo.explicit_policy_days("", StreamKind.KLINES.value)
        if days is None:
            return None
        return RetentionPolicy([], [RetentionRule(StreamKind.KLINES, days, None)])

    return load


def wire_public_ws(
    ctx: AppContext, kline_boundary: KlineHotBoundary | None = None
) -> ConnectionManager:
    """E08-T04 (flag `ingestion_ws_enabled`, default off — C-4.13): compose the
    public WS skeleton. The exchange adapter (M4) supplies the socket factory and
    topic vocabulary; ingestion (M6) owns the connection lifecycle and is
    started/stopped by the module supervisor (tracked tasks, bounded frame
    queue — C-2.18). Public stream only: no credentials are involved."""
    env = ctx.settings.environment.value
    clock = time.monotonic
    adapter = ctx.exchange_bybit
    watchdog = StalenessWatchdog(clock, lambda _e: None, kind_of=adapter.topic_kind)
    manager = ConnectionManager(
        adapter.public_socket_factory(env, max_frame_bytes=MAX_FRAME_BYTES),
        SubscriptionPlanner(),
        watchdog,
        ReconnectPolicy(),
        ConnectionRateGuard(clock),
        ctx.ingestion.offer_frame,
        bus=ctx.bus.bus,
        env=env,
    )
    ctx.ingestion.attach_ws(manager)
    ingest_enabled.set(1.0)  # silent-death meta-alert keys on this (E08-T06)
    # E04-T06: measure the exchange clock offset (public /v5/market/time, no
    # credentials) so the exchange latency stage is available; started and
    # stopped with ingestion. Public data always uses the live host (demo has
    # no separate public feed).
    rest = adapter.public_rest_client(env)
    guard = wire_clock_offset(ctx, rest_client_fetcher(rest))
    ctx.ingestion.attach_closer(rest.aclose)

    def _is_listed(symbol: str) -> bool:
        # Only catalogue symbols may become topics (E08-S03 security note).
        scheduler = ctx.ingestion.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        inst = snap.get(symbol) if snap is not None else None
        return inst is not None and inst.status == "trading"

    class _TickerWriter:
        """Write-behind to the hot tier incl. best bid/ask (21-database-schema.md `tickers`)."""

        async def write_ticker(self, event: TickerEvent) -> None:
            zero = "0"
            await ctx.storage.market_data.write_tickers(
                [
                    TickerRow(
                        ts_us=event.ts_event,
                        symbol=event.symbol,
                        last_price=str(event.last_price or zero),
                        mark_price=str(event.mark_price or zero),
                        index_price=str(event.index_price or zero),
                        funding_rate=str(event.funding_rate or zero),
                        open_interest=str(event.open_interest or zero),
                        bid1_price=None if event.bid1_price is None else str(event.bid1_price),
                        bid1_size=None if event.bid1_qty is None else str(event.bid1_qty),
                        ask1_price=None if event.ask1_price is None else str(event.ask1_price),
                        ask1_size=None if event.ask1_qty is None else str(event.ask1_qty),
                    )
                ]
            )

    # Each stream owns a slice of the upstream topic set; the socket gets the union.
    demand: dict[str, set[str]] = {}

    def _set_desired(stream: str, topics: set[str]) -> None:
        demand[stream] = set(topics)
        manager.set_desired(set().union(*demand.values()))

    class _TradeWriter:
        """Batched write-behind to the hot tier (21-database-schema.md `trades`)."""

        async def write_trades(self, events: Sequence[TradeEvent]) -> None:
            await ctx.storage.market_data.write_trades(
                [
                    TradeRow(
                        ts_us=e.ts_event,
                        symbol=e.symbol,
                        price=str(e.price),
                        qty=str(e.qty),
                        side=e.side,
                        trade_id=e.trade_id,
                    )
                    for e in events
                ]
            )

    def _tick_size(symbol: str) -> Decimal | None:
        scheduler = ctx.ingestion.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        inst = snap.get(symbol) if snap is not None else None
        return None if inst is None else inst.tick_size

    def _launch_us(symbol: str) -> int | None:
        scheduler = ctx.ingestion.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        inst = snap.get(symbol) if snap is not None else None
        return None if inst is None else int(inst.launch_time)

    _wire_klines(ctx, adapter.kline_fetcher(rest, _tick_size), kline_boundary)

    # #1892/#1912: wall clock (not the monotonic demand clock) bounds event time,
    # shifted by ClockGuard's measured offset so the exchange clock is truth.
    window = EventWindow(corrected_now_us(guard.offset_us), _launch_us)

    ctx.ingestion.attach_trades(
        TradeStream(
            bus=ctx.bus.bus,
            env=env,
            set_desired=lambda topics: _set_desired("trade", topics),
            parse_frame=adapter.parse_trade_frame,
            topic_for=adapter.trade_topic,
            is_listed=_is_listed,
            touch=watchdog.touch,
            fetch_recent=adapter.recent_trades_fetcher(rest.get_public),
            tick_size=_tick_size,
            clock=clock,
            event_window=window,
            writer=_TradeWriter(),
        )
    )

    class _BookWriter:
        """Write-behind to the hot tier (21-database-schema.md `orderbook_*`)."""

        async def write_book_deltas(self, rows: Sequence[BookDeltaRow]) -> None:
            await ctx.storage.market_data.write_book_deltas(rows)

        async def write_book_snapshot(self, row: BookSnapshotRow) -> None:
            await ctx.storage.market_data.write_book_snapshot(row)

    ctx.ingestion.attach_books(
        BookStream(
            bus=ctx.bus.bus,
            env=env,
            set_desired=lambda topics: _set_desired("book", topics),
            parse_frame=lambda f: adapter.parse_book_frame(f, _tick_size),
            topic_for=adapter.book_topic,
            resubscribe=manager.resubscribe_topic,
            is_listed=_is_listed,
            touch=watchdog.touch,
            clock=clock,
            writer=_BookWriter(),
            supervisor=B14BookSupervisor(),
        )
    )
    ctx.ingestion.attach_tickers(
        TickerStream(
            bus=ctx.bus.bus,
            env=env,
            set_desired=lambda topics: _set_desired("ticker", topics),
            parse_frame=adapter.parse_ticker_frame,
            topic_for=adapter.ticker_topic,
            is_listed=_is_listed,
            touch=watchdog.touch,
            clock=clock,
            event_window=window,
            writer=_TickerWriter(),
        )
    )
    # #1916/#1905: per-topic dispatch lanes behind the pump; the pump touches
    # the watchdog on routing, so freshness reflects the venue.
    ctx.ingestion.attach_router(adapter.frame_route, watchdog.touch)
    return manager


def _wire_klines(
    ctx: AppContext, fetch_klines: KlineFetcher, kline_boundary: KlineHotBoundary | None = None
) -> None:
    """E12-S05: cache-first `/market/klines` with background exchange backfill.

    The hot tier is both the backfill cache and the read source; pages are written as
    `source=rest` kline rows. Persisting kline-sourced `bars_time` rows (`bars.kline_rows`) is
    wired once a `BarWriter` is composed (E12-T05), so no `kline_sink` here yet.
    """

    class _HotKlines:
        async def read_klines(
            self, sym: str, interval: str, rng: Range, tier: str = "auto", limit: int | None = None
        ) -> Sequence[KlineRow]:
            return await ctx.storage.market_data.read_klines(
                sym, interval, TimeRange(start_us=rng.start_us, end_us=rng.end_us), limit=limit
            )

        async def write_klines(self, rows: Sequence[object]) -> None:
            await ctx.storage.market_data.write_klines(
                [KlineRow(**cast(dict[str, Any], r)) for r in rows]
            )

    hot = _HotKlines()
    boundary = kline_boundary if kline_boundary is not None else KlineHotBoundary()
    backfill = KlineBackfillService(fetch_klines=fetch_klines, cache=hot)
    cold = ParquetKlineReader(
        DatasetRegistry(ctx.settings.parquet_root),
        max_concurrency=ctx.settings.cold_kline_concurrency,
    )
    ctx.ingestion.attach_klines(
        KlineReadService(
            hot,
            backfill=backfill,
            cold=cold,
            # #2060: klines hot window from the DB-seeded retention policy (21 §7), 90 d fallback;
            # older windows read from Parquet.
            hot_boundary_us=boundary.boundary_us,
            recording_started_at_us=recording_started_at_us(ctx),
        ),
        backfill,
    )


def recording_started_at_us(ctx: AppContext) -> RecordingStart:
    """E12-S05 `meta.recording_started_at`: the EARLIEST of (a) the oldest trade in the hot
    `trades` tape (`first_trade_us`) and (b) E16-T04's `min(first_event_ts)` across the
    symbol's recording sessions when `CoverageService` is composed. Sessions only win when
    present and earlier: until the session manager is wired into the lifespan (#2188) no
    session rows are written, and the tape remains the source (no false `no_data_recorded`).
    `None` only when neither source knows of any recorded data."""

    async def first(symbol: str) -> int | None:
        tape = await ctx.storage.market_data.first_trade_us(symbol)
        cov = ctx.recorder.coverage
        sessions = await cov.recording_started_at_us(symbol) if cov is not None else None
        known = [v for v in (tape, sessions) if v is not None]
        return min(known) if known else None

    return first


def wire_clock_offset(ctx: AppContext, fetch_server_time: ServerTimeFetcher) -> ClockGuard:
    """E04-T06: compose ClockGuard over the adapter's REST server-time fetcher
    (`rest_client_fetcher`); its offset corrects the exchange latency stage.
    The guard's periodic task is started by whoever owns the REST client."""
    guard = ClockGuard(fetch_server_time)
    ctx.ingestion.attach_clock(guard)
    return guard
