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
import contextlib
import functools
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, cast

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import State
from starlette.types import ASGIApp

from candleviewer.account_fixture_wiring import AccountFixture, build_account_fixture
from candleviewer.account_health_wiring import wire_account_health
from candleviewer.accounts.key_age import KeyRotationPolicy
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.service import AccountsService
from candleviewer.accounts.status import AccountStatusReader
from candleviewer.admin.account_access import AccountAccessService
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.flags import default_registry
from candleviewer.admin.flags.metrics import export_flag_metrics
from candleviewer.admin.flags.push import feature_flags_snapshot
from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.admin.lifecycle_metrics import export_user_lifecycle_metrics
from candleviewer.admin.ops.health import AdminHealthService
from candleviewer.admin.ops.incident_metrics import export_incident_metrics
from candleviewer.admin.overview.metrics import export_overview_metrics
from candleviewer.admin.service import AdminService
from candleviewer.admin.wiring import (
    AuditHandle,
    AuditVerifyRunner,
    LaneNotWired,
    SecretsBundle,
    SecretsHandle,
    audit_writer_sink,
    build_audit_service,
    build_audit_verify_job,
    build_secrets_service,
    export_audit_lane_metrics,
    export_secrets_metrics,
    secrets_audit_row,
    system_event_redactor,
)
from candleviewer.admin_wiring import (
    build_admin_incidents,
    build_admin_read_models,
    build_open_incidents_gauge,
    build_statechart_inspector,
    build_system_settings,
)
from candleviewer.alerts.dispatcher import AlertDispatcher, default_adapters
from candleviewer.alerts.evaluator import AlertEvaluator, AlertMetrics
from candleviewer.alerts.lifecycle import AlertCharts
from candleviewer.alerts.outbox import TOPIC_ALERT_DELIVER, alert_deliver_dedup_key
from candleviewer.alerts.owners import OwnerGate
from candleviewer.alerts.ports import FiringStore, WakingFiringStore
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
from candleviewer.api.admin_backup_delete import make_admin_backup_delete_router
from candleviewer.api.admin_backup_download import (
    NoStoreNoReferrer,
    make_admin_backup_download_router,
)
from candleviewer.api.admin_backup_links import make_admin_backup_links_router
from candleviewer.api.admin_backup_verify import make_admin_backup_verify_router
from candleviewer.api.admin_backups import make_admin_backup_runs_router, make_admin_backups_router
from candleviewer.api.admin_capacity import make_admin_capacity_router
from candleviewer.api.admin_jobs import LostJobsCount, make_admin_jobs_router
from candleviewer.api.admin_kek import make_admin_kek_router
from candleviewer.api.admin_ops import make_admin_incident_ack_router, make_admin_ops_router
from candleviewer.api.admin_overview import make_admin_overview_router
from candleviewer.api.admin_statecharts import make_statechart_router
from candleviewer.api.alert_deliveries import make_alert_deliveries_router
from candleviewer.api.alerts import make_alerts_router
from candleviewer.api.audit_budget import AuditBudgetFlushTask, AuditRecordBudget
from candleviewer.api.audit_exports import AuditExports, ExportSigning
from candleviewer.api.audit_limiter import AuditQueryLimiter, AuditVerifyLimiter
from candleviewer.api.audit_principal import SessionAuditPrincipalResolver
from candleviewer.api.audit_signing_keys import make_audit_signing_router
from candleviewer.api.audit_verify_runner import ChainVerifyRunner
from candleviewer.api.auth_perf import auth_perf_enabled, make_auth_perf_router
from candleviewer.api.contract_conformance import load_contract_subset
from candleviewer.api.cors import CorsGateMiddleware, CorsPolicy
from candleviewer.api.csrf import CsrfMiddleware, RefusalAuditTracker
from candleviewer.api.deny_by_default import (
    assert_app_routes_declared,
    declared_operations,
    make_deny_undeclared_dependency,
    rbac_permissions,
)
from candleviewer.api.drawings import make_drawings_router
from candleviewer.api.drawings_models import TOOLS
from candleviewer.api.enrolment_guard import (
    EnrolmentRefusals,
    make_enrolment_only_guard,
    sessionless_operations,
)
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.api.exchange_accounts import make_exchange_accounts_router
from candleviewer.api.exchange_keys import make_exchange_keys_router
from candleviewer.api.feature_flags import make_feature_flags_routers
from candleviewer.api.hotkey_audit import make_hotkey_audit_router
from candleviewer.api.idle_lock import IdleLockMiddleware
from candleviewer.api.indicator_presets import make_indicator_presets_router
from candleviewer.api.indicator_presets_service import (
    IndicatorPresetMetrics,
    IndicatorPresetsGaugePrimer,
)
from candleviewer.api.indicators import make_indicators_router
from candleviewer.api.invites import make_invites_router
from candleviewer.api.market_bars import TradeTotalsSource, make_market_bars_router
from candleviewer.api.market_coverage import make_data_coverage_router
from candleviewer.api.me import make_me_router
from candleviewer.api.notifications import make_notifications_router
from candleviewer.api.onboarding import make_onboarding_router
from candleviewer.api.onboarding_checklist import StepResult, bybit_key_restriction
from candleviewer.api.openapi_publish import install_contract_openapi
from candleviewer.api.order_cancel_all import make_cancel_all_router
from candleviewer.api.order_exits import make_order_exits_router
from candleviewer.api.order_principal import SessionTradingPrincipalResolver
from candleviewer.api.orders import OrderPrincipals, make_orders_router
from candleviewer.api.profile_writes import SaveMeasures, make_profile_writes_router
from candleviewer.api.profiles import make_profiles_router
from candleviewer.api.recorder_admin import AdminJobStore, make_recorder_admin_router
from candleviewer.api.recorder_purge import make_recorder_purge_router
from candleviewer.api.recording_reports import make_recording_reports_router
from candleviewer.api.recording_retention import make_recording_retention_router
from candleviewer.api.recording_status import make_recording_status_router
from candleviewer.api.recording_symbols import make_recording_symbols_router
from candleviewer.api.recording_writes import make_recording_writes_router
from candleviewer.api.response_headers import NoSniff
from candleviewer.api.rules_actor import SessionRulesActorResolver, make_rules_audit
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.api.session_backstop_audit import SessionBackstopAudit
from candleviewer.api.session_snapshot import SessionSnapshotResolver
from candleviewer.api.sessions import AuditEmitter, make_session_router
from candleviewer.api.step_up import (
    SpentGrant,
    make_read_only_guard,
    make_step_up_router,
    request_elevation,
    require_bound_elevation,
    require_session_elevation,
    step_up_port,
)
from candleviewer.api.support_bundle import make_support_bundle_router
from candleviewer.api.telemetry import SessionKeyResolver, make_telemetry_router
from candleviewer.api.users import (
    AccountAccessStore,
    PermissionChangeNotifier,
    SnapshotResolver,
    UserDisable,
    UserRoleStore,
    make_user_admin_router,
    make_users_router,
)
from candleviewer.api.view_as import make_view_as_router, make_view_as_start_router
from candleviewer.api.view_as_guard import make_view_as_guard, view_as_unstamped_handler
from candleviewer.api.view_as_policy import ProtectiveWrites
from candleviewer.api.view_as_refusals import ViewAsRefusalRecorder
from candleviewer.api.view_as_subject import TargetNamedAsActor, ViewAsUnstamped, acting_user
from candleviewer.api.workspaces import OPERATIONS, make_workspaces_router
from candleviewer.audit_lane_wiring import lane_key_loader
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.metrics import export_auth_metrics
from candleviewer.auth.models import (
    InviteRecord,
    MfaChallengeRecord,
    MfaMethodRecord,
    SessionRecord,
    UserRecord,
)
from candleviewer.auth.owner_floor import assert_owner_floor
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.auth.session_service import (
    ACCESS_TOKEN_TTL,
    SessionClass,
    access_token_expires_at,
)
from candleviewer.auth.testnet_clock import audit_test_clock_enabled, build_test_clock
from candleviewer.auth.view_as import current_view_as
from candleviewer.backups_wiring import (
    build_admin_backups,
    build_backup_deletion,
    build_backup_downloads,
    build_backup_fetch,
    build_backup_freshness,
    build_backup_runs,
    build_backup_verifications,
    serve_backup_metrics,
)
from candleviewer.bars.limits import QUERY_TIMEOUT_S
from candleviewer.bars.metrics import export_bars_metrics
from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import BarReader, tape_time_bar_reader
from candleviewer.bars.series_store import RepairHook, SeriesStore
from candleviewer.bars.service import BarsService
from candleviewer.bars_wiring import wire_bars
from candleviewer.book.service import BookService
from candleviewer.budget_wiring import build_disk_budget
from candleviewer.bus.models import Topic
from candleviewer.bus.service import BusService
from candleviewer.domain.events import InstrumentUpdatedEvent
from candleviewer.exchange.base.instruments import InstrumentsFetcher, RiskLimitsFetcher
from candleviewer.exchange.base.models import TickerEvent, TradeEvent
from candleviewer.exchange.base.service import ExchangeBaseService

# Composition root: wires the one concrete exchange adapter (C-2.2).
# nosemgrep: cv-adapter-isolation reason=B5-b owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.flags_wiring import build_feature_flags, restate_flag_write
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
    register_recorder_probe,
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
from candleviewer.ingestion.reconnect import ReconnectPolicy
from candleviewer.ingestion.rejection import EventWindow, corrected_now_us
from candleviewer.ingestion.service import IngestionService
from candleviewer.ingestion.ticker_stream import TickerStream
from candleviewer.ingestion.trade_stream import TradeStream
from candleviewer.ingestion.watchdog import StalenessWatchdog
from candleviewer.journal.service import JournalService
from candleviewer.key_import_wiring import wire_key_import
from candleviewer.key_selfcheck_wiring import wire_key_selfcheck
from candleviewer.key_test_wiring import wire_key_test
from candleviewer.machine_state_wiring import RegistryFeed
from candleviewer.net import (
    BindingSelfCheck,
    CidrAllowList,
    MeshOnlyMiddleware,
    MeshSelfCheckScheduler,
    ReadOnlyGate,
    SystemTopicPublisher,
    export_net_metrics,
    net_binding_safe,
    real_socket_enumerator,
    register_system_topic_subscriber,
)
from candleviewer.net.system_topic import client_notice
from candleviewer.observability.audit_query_metrics import export_audit_query_metrics
from candleviewer.observability.authz_denials import METRIC_NAME as AUTHZ_DENIALS_METRIC
from candleviewer.observability.authz_denials import AuthzDenialMiddleware
from candleviewer.observability.correlation import CorrelationMiddleware
from candleviewer.observability.health_metrics import bind_health_metrics
from candleviewer.observability.health_probes import HealthRegistry
from candleviewer.observability.http_duration import (
    METRIC_NAME as HTTP_DURATION_METRIC,
)
from candleviewer.observability.http_duration import HttpDurationMiddleware
from candleviewer.observability.latency import StageRecorder
from candleviewer.observability.log_level import LogLevelOverrides
from candleviewer.observability.metrics import CollectorRegistry, Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.observability.service import ObservabilityService
from candleviewer.observability.support_bundle import filter_config
from candleviewer.observability.support_bundle_wiring import build_support_bundle_service
from candleviewer.observability.telemetry import SessionRateLimiter, TelemetrySink
from candleviewer.oms.service import OmsService
from candleviewer.oms_wiring import OmsAudit, OmsRuntime, build_oms_runtime
from candleviewer.orderbook_wiring import BookStream
from candleviewer.orderflow.indicators.catalogue import default_catalogue
from candleviewer.orderflow.indicators.engine import IndicatorEngine, StoredHistory
from candleviewer.orderflow.indicators.metrics import export_indicator_metrics
from candleviewer.orderflow.service import OrderflowService
from candleviewer.paper.service import PaperService
from candleviewer.profile_notices_wiring import ProfileNotices
from candleviewer.profile_warnings_wiring import SaveTimeFigures
from candleviewer.profiles_wiring import profile_writes, wire_profiles
from candleviewer.recorder.control import RecordingControl, StoredRecordingControl
from candleviewer.recorder.control_runtime import RecorderWiring, RuntimeRecordingControl
from candleviewer.recorder.coverage import CoverageService
from candleviewer.recorder.metrics import current_write_backlog_rows, export_recorder_metrics
from candleviewer.recorder.policy import PolicyConfig
from candleviewer.recorder.service import RecorderService
from candleviewer.recorder.status import RecordingStatusCache
from candleviewer.recorder_wiring import (
    ComposedRecorder,
    build_recorder,
    policy_config,
    questdb_sinks,
)
from candleviewer.replay.metrics import export_replay_metrics
from candleviewer.replay.service import ReplayService
from candleviewer.replay.sessions_service import LANE as REPLAY_LANE
from candleviewer.replay.sessions_service import (
    ReplayLimits,
    ReplaySessionService,
    WindowCoverage,
)
from candleviewer.retention_wiring import (
    build_compactor,
    build_purge_anchors,
    build_retention_manager,
)
from candleviewer.risk.service import RiskService
from candleviewer.rolloff_wiring import build_rolloff_job
from candleviewer.rules.manager import Actor
from candleviewer.rules.service import RulesService
from candleviewer.rules_store_pg import PostgresRuleStore
from candleviewer.settings import (
    STOP_SLACK_S,
    TEARDOWN_BUDGET_S,
    Environment,
    FeedMode,
    Settings,
    get_settings,
)
from candleviewer.statechart.bindings.b16_session import set_audit_sink as set_b16_audit_sink
from candleviewer.statechart.gateway import (
    ALWAYS_ADMIT,
    Gateway,
    GatewayDegradedError,
    GatewayOverloadedError,
)
from candleviewer.statechart.persistence import HmacKeys
from candleviewer.statechart.plugins import MachineStatePort
from candleviewer.statechart_wiring import StatechartPersistence, build_statechart_persistence
from candleviewer.storage.cold.archive_import import FileImportLedger
from candleviewer.storage.cold.compaction_run import compact_all
from candleviewer.storage.cold.kline_reader import ParquetKlineReader
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.observability import LoggingSystemEventSink
from candleviewer.storage.cold.scrub import ScrubTask
from candleviewer.storage.cold.watermarks import FileWatermarkStore
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.wiring import LazyPgWire, QuestDbRowSink
from candleviewer.storage.repositories.account_access_sqlalchemy import (
    SqlAlchemyAccountAccessStore,
)
from candleviewer.storage.repositories.accounts_sqlalchemy import SqlAlchemyAccountsStore
from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import (
    SqlAlchemyAlertDeliveryRepository,
)
from candleviewer.storage.repositories.alert_dispatch_sqlalchemy import (
    SqlAlchemyAlertDispatchStore,
)
from candleviewer.storage.repositories.alert_firing_sqlalchemy import SqlAlchemyAlertFiringStore
from candleviewer.storage.repositories.alerts_sqlalchemy import SqlAlchemyAlertRepository
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.auth_keys_sqlalchemy import SqlAlchemyAuthKeyStore
from candleviewer.storage.repositories.break_glass_sqlalchemy import SqlAlchemyBreakGlassEvents
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.drawings_sqlalchemy import SqlAlchemyDrawingRepository
from candleviewer.storage.repositories.export_keys_sqlalchemy import SqlAlchemyExportKeyStore
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.incidents_sqlalchemy import SqlAlchemyIncidents
from candleviewer.storage.repositories.indicator_presets_sqlalchemy import (
    SqlAlchemyIndicatorPresetRepository,
)
from candleviewer.storage.repositories.instruments_sqlalchemy import (
    SqlAlchemyInstrumentsRepository,
)
from candleviewer.storage.repositories.invites_sqlalchemy import SqlAlchemyInviteRepository
from candleviewer.storage.repositories.mfa_sqlalchemy import SqlAlchemyMfaRepository
from candleviewer.storage.repositories.notifications_sqlalchemy import (
    SqlAlchemyNotificationRepository,
)
from candleviewer.storage.repositories.onboarding_sqlalchemy import SqlAlchemyOnboardingStore
from candleviewer.storage.repositories.order_path_symbols_sqlalchemy import (
    SqlAlchemyOrderPathSymbols,
)
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository
from candleviewer.storage.repositories.recording_reads_sqlalchemy import SqlAlchemyRecordingReads
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.replay_sessions_sqlalchemy import (
    SqlAlchemyReplaySessionRepository,
)
from candleviewer.storage.repositories.retention_policies_sqlalchemy import (
    SqlAlchemyRetentionPolicies,
)
from candleviewer.storage.repositories.rows import (
    BookDeltaRow,
    BookSnapshotRow,
    KlineRow,
    TickerRow,
    TradeRow,
    TradeTotals,
)
from candleviewer.storage.repositories.rules_sqlalchemy import SqlAlchemyRulesRepository
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource
from candleviewer.storage.repositories.sessions_sqlalchemy import (
    SqlAlchemySessionRepository,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import SqlAlchemyUserRoleStore
from candleviewer.storage.repositories.users_sqlalchemy import (
    SqlAlchemyUserAdminStore,
    SqlAlchemyUserRepository,
)
from candleviewer.storage.repositories.workspaces_sqlalchemy import SqlAlchemyWorkspaceRepository
from candleviewer.storage.retention.alert_tasks import AlertDeliveriesPurgeTask, AlertGaugeTask
from candleviewer.storage.retention.drawings_tasks import DrawingsMetrics, DrawingsPurgeTask
from candleviewer.storage.retention.incidents_tasks import IncidentsPurgeTask
from candleviewer.storage.retention.kline_boundary import (
    KlineBoundaryRefreshTask,
    KlineHotBoundary,
)
from candleviewer.storage.retention.policy import RetentionPolicy, RetentionRule
from candleviewer.storage.retention.rule_prune import RulePruneTask
from candleviewer.storage.retention.schedule import RetentionSchedule
from candleviewer.storage.retention.workspaces_tasks import (
    USER_BUCKETS,
    WorkspacesMetrics,
    WorkspacesPurgeTask,
)
from candleviewer.storage.service import StorageService
from candleviewer.user_cascade_wiring import build_user_disable_service, build_users_purge_task
from candleviewer.view_as_wiring import (
    IdentityLabels,
    RoleChangeNotifier,
    SessionViewAs,
    SessionViewAsRefusals,
    build_view_as,
)
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.bars_publish import BarsPublisher
from candleviewer.ws.bars_source import BarsSnapshotSource
from candleviewer.ws.gateway import (
    WS_PATH,
    Authenticate,
    AuthRefused,
    GatewayHub,
    include_ws_router,
    make_ws_router,
)
from candleviewer.ws.indicators_publish import IndicatorsPublisher
from candleviewer.ws.indicators_source import IndicatorsSnapshotSource
from candleviewer.ws.machines import MachineStateRegistry
from candleviewer.ws.metrics import export_cvwb_metrics, export_ws_metrics
from candleviewer.ws.origin_audit import OriginRefusalAudit
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub, SnapshotSource, new_span_id
from candleviewer.ws.service import WsService
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import (
    IngestionUpstreamSink,
    KillSwitchView,
    MachineRevocationAudit,
    StorePrincipalLoader,
    WsEvents,
    WsRuntime,
    alerts_topic,
    book_snapshot_source,
    default_snapshot_router,
    ingestion_streams,
    loop_call_later,
    recorder_topic,
    wallet_topic,
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


def _oms_state(runtime: OmsRuntime | None) -> str | None:
    """`/readyz`'s `oms` check: the runtime's state while it runs, else no check."""
    return runtime.state if runtime is not None and runtime.started else None


def bind_recording_runtime(
    state: State, wiring: RecorderWiring | None, config: PolicyConfig
) -> None:
    """E16-T08 S9 (#492): with #2188's composed recorder, one `RuntimeRecordingControl` serves
    the recorded-set reads, the writes and the status (`state` is `app.state`). Without it nothing
    changes: the stored reads stay, the writes answer 503 and the status `not_deployed`."""
    if wiring is None:
        return
    control = RuntimeRecordingControl(wiring, config=config, now=lambda: datetime.now(UTC))
    state.recording_control = state.recording_writer = state.recording_runtime = control


def recording_writer(state: State) -> RecordingControl | None:
    """The control the writes route reads per request (`state` is `app.state`): none, so `503`,
    until the recorder's startup has completed, while its memory still lacks the stored rows and a
    remove or an unpin would change nothing (SEC-4, #2188). `recording_ready` is read each time."""
    control: RecordingControl | None = state.recording_writer if state.recording_ready() else None
    return control


def _same_user(value: object, user: uuid.UUID) -> bool:
    """`value` names `user` in any form the writer stores as that id (`UUID`, or any spelling of
    it: case, braces, `urn:uuid:`); a value that is no id names no user."""
    try:
        return uuid.UUID(str(value)) == user
    except ValueError:
        return False


def _refuse_target_as_actor(action: str, fields: dict[str, Any]) -> None:
    """The tripwire behind every audit write (#3085 S8): while a view-as context is bound, no
    record may name its target as the actor."""
    ctx = current_view_as()
    actor = fields.get("actor_user_id")
    if ctx is not None and actor is not None and _same_user(actor, ctx.target_user_id):
        structlog.get_logger(__name__).error("audit.view_as_target_named_actor", action=action)
        raise TargetNamedAsActor(action)


class _LazyAuditEmitter:
    """Resolves `audit.writer` per call: it only exists once `AuditService.start()` ran. Every
    write passes the view-as tripwire first (`_refuse_target_as_actor`)."""

    def __init__(self, audit: AuditHandle) -> None:
        self._audit = audit

    async def emit(self, action: str, **kwargs: Any) -> None:
        _refuse_target_as_actor(action, kwargs)
        await self._audit.writer.emit(action, **kwargs)

    async def emit_keyed(self, action: str, name: str, **kwargs: Any) -> None:
        _refuse_target_as_actor(action, kwargs)
        await self._audit.writer.emit_keyed(action, name, **kwargs)  # #3085: one per context


class _LazyLaneEmitter:
    """Resolves `audit.lane` per call, for a row the lane's registry admits (ADR-0037): the façade,
    whose fallback is the writer. With no façade (`LaneNotWired`: before `start()`, once `stop()`
    began) the writer takes the row, today's path, logged once."""

    def __init__(self, audit: AuditHandle) -> None:
        self._audit, self._unwired_logged = audit, False

    async def emit(self, action: str, **kwargs: Any) -> None:
        sink: AuditEmitter
        try:
            sink = self._audit.lane
        except LaneNotWired:  # only this: any other error is a defect and propagates
            if not self._unwired_logged:
                self._unwired_logged = True
                with contextlib.suppress(Exception):  # a failing logger changes nothing
                    structlog.get_logger(__name__).warning("audit.lane.unwired", action=action)
            sink = self._audit.writer
        await sink.emit(action, **kwargs)  # the one write, outside the handler


class _LazyAuditQuery:
    """Resolves `audit.query` per call, as `_LazyAuditEmitter` does the writer (BK-9's evidence)."""

    def __init__(self, audit: AuditHandle) -> None:
        self._audit = audit

    async def query(self, **kwargs: Any) -> Any:  # an `AuditPage`: `app` may not import `audit`
        return await self._audit.query.query(**kwargs)


class _ReplayCoverage:
    """E26-T01: `replay.CoverageReader` over E16-T04 `CoverageService` (M12 may not import the
    recorder, C-3.1): the recorded `trades` intervals of the window; the rest is a gap."""

    def __init__(self, coverage: CoverageService) -> None:
        self._coverage = coverage

    async def window(self, symbol: str, lo_us: int, hi_us: int) -> WindowCoverage:
        [trades] = await self._coverage.coverage(symbol, [StreamKind.TRADES.value], lo_us, hi_us)
        return WindowCoverage(covered=tuple((i.lo, i.hi) for i in trades.intervals))


def _build_replay_sessions(
    settings: Settings,
    pg: SqlAlchemyRelationalRepository,
    coverage: CoverageService,
    audit: AuditHandle,
    feed: MachineStatePort | None = None,
    persistence: StatechartPersistence | None = None,
) -> ReplaySessionService:
    """E26-T01: the B12 session lifecycle. Paper-account grants and source handles are ports
    E26-T05/E36 wire: until then a paper-trading session is refused (fail closed). E50-T63: with
    the persistence bundle, sessions are persisted and restored through it (its `control`-lane
    `Restorer`) and their gateway refuses a chain-trip-latched session's gated events; without
    it (no HMAC keys) persist and restore stay unwired."""
    limits = ReplayLimits(
        idle_ttl=timedelta(seconds=settings.replay_idle_ttl_s),
        max_sessions_per_user=settings.replay_max_sessions_per_user,
        max_window=timedelta(hours=settings.replay_max_window_hours),
        reclaim_interval_s=settings.replay_reclaim_interval_s,
        max_lifetime=timedelta(seconds=settings.replay_max_lifetime_s),
    )
    return ReplaySessionService(
        SqlAlchemyReplaySessionRepository(pg),
        coverage=_ReplayCoverage(coverage),
        audit=_LazyAuditEmitter(audit),
        limits=limits,
        gateway=Gateway(admission=persistence.admission if persistence else ALWAYS_ADMIT),
        env=settings.environment.value,
        machine_feed=feed,
        snapshots=persistence.snapshots if persistence else None,
        restorer=persistence.restorer(REPLAY_LANE) if persistence else None,
        persister=persistence.persister if persistence else None,
    )


def _attach_replay_sessions(
    ctx: AppContext,
    settings: Settings,
    pg: SqlAlchemyRelationalRepository | None,
    coverage: CoverageService | None,
    feed: MachineStatePort | None = None,
    persistence: StatechartPersistence | None = None,
) -> None:
    """Replay sessions need Postgres and the recorded-coverage service (real backend only);
    without them the module stays scaffold-only and nothing is attached."""
    if pg is not None and coverage is not None:
        sessions = _build_replay_sessions(settings, pg, coverage, ctx.audit, feed, persistence)
        ctx.replay.attach_sessions(sessions)


def _audit_ready(audit: AuditHandle) -> Callable[[], bool]:
    """#2492 (C-2.9): an owner action whose audit record cannot be written is refused
    before it changes anything: the writer is started, its flusher has not died and
    (#2510) no WAL append failed within `APPEND_FAILURE_COOLDOWN` (it then re-probes)."""
    return lambda: (
        audit.is_active
        and getattr(audit.writer, "failure", None) is None
        and not getattr(audit.writer, "append_failure_active", False)
    )


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
        # #2146: a TOTP clock-skew event is a `system_events` row (the health board's table).
        system_events=PgSystemEventWriter(relational, redact_details=system_event_redactor()),
        # E09-S11 (O4): whether a break-glass reset is unresolved, for the WS `system` notice.
        break_glass_events=SqlAlchemyBreakGlassEvents(relational),
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


def build_user_role_store(settings: Settings) -> SqlAlchemyUserRoleStore | None:
    """#2492: the Postgres `UserRoleStore` behind `PUT /users/{userId}/roles` and the
    owner TOTP-reset target lookup, with the M18 owner floor injected (M10 may not
    import `auth`). `None` on the fake backend, where those routes fail closed (501)."""
    if settings.storage_backend != "real":
        return None
    return SqlAlchemyUserRoleStore(
        SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "user-roles"),
        owner_floor=lambda current, new, owners: assert_owner_floor(
            current_roles=current, new_roles=new, active_owner_count=owners
        ),
    )


def build_user_admin_store(settings: Settings) -> SqlAlchemyUserAdminStore | None:
    """E42-T09 (#2649): the Postgres `UserAdminStore` behind `GET`/`PATCH /users/{userId}` and the
    admin session routes, with the M18 owner floor injected; `None` on the fake backend, where
    those routes fail closed (501). No I/O at construction: the engine connects lazily."""
    if settings.storage_backend != "real":
        return None
    return SqlAlchemyUserAdminStore(
        SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "user-admin"),
        owner_floor=lambda current, new, owners: assert_owner_floor(
            current_roles=current, new_roles=new, active_owner_count=owners
        ),
    )


def build_account_access_store(
    settings: Settings, audit: AuditHandle
) -> SqlAlchemyAccountAccessStore | None:
    """E42-T08 (#2648): the Postgres store behind `/users/{userId}/account-access`; `None` on the
    fake backend, where the route fails closed (501). No I/O at construction."""
    if settings.storage_backend != "real":
        return None
    return SqlAlchemyAccountAccessStore(
        SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "account-access"),
        audit=_LazyAuditEmitter(audit),
    )


def _build_accounts_counts(settings: Settings) -> SqlAlchemyAccountsStore | None:
    """#2314: the M13 row-gauge source (aggregate counts, never a row); `None` on the fake
    backend. No I/O at construction: the engine connects lazily."""
    if settings.storage_backend != "real":
        return None
    return SqlAlchemyAccountsStore(
        SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "accounts")
    )


def _build_incidents_purge(settings: Settings) -> IncidentsPurgeTask | None:
    """E42-T05: resolved incidents dropped `policy.INCIDENTS_RESOLVED_MONTHS` after
    `last_seen_at` (21 Sec.7), started by the lifespan when retention is enabled; `None` on the
    fake backend (no `incidents` table). `incidents` has no forbid-delete trigger, so the app DSN
    may purge. No I/O here."""
    if settings.storage_backend != "real":
        return None
    relational = SqlAlchemyRelationalRepository(
        settings.pg_dsn.get_secret_value(), "incidents-retention"
    )
    return IncidentsPurgeTask(
        SqlAlchemyIncidents(relational), RetentionSchedule.from_settings(settings)
    )


def _build_audit(settings: Settings) -> AuditHandle:
    """QA #1658 (C-2.9): the real hash-chained audit sink on the real backend. ADR-0037: its
    `start()` runs the lane key loader on every backend (S2b-1's refusals)."""
    keys = lane_key_loader(settings)
    if settings.storage_backend != "real":
        return build_audit_service(lane_keys=keys)
    return build_audit_service(
        SqlAlchemyAuditRepository(
            SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "audit"),
            read_slots=settings.audit_query_global_max_concurrent,
            verify_read_timeout_ms=settings.audit_verify_statement_timeout_ms,
            verify_max_entry_bytes=settings.audit_verify_max_entry_bytes,
        ),
        lane_keys=keys,
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
    relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "secrets")
    audit_row = secrets_audit_row(settings.environment.value)
    store = SqlAlchemyCredentialStore(relational, audit_row=audit_row)  # #2266: in-tx records
    # #3505: a KEK re-wrap run counts this environment's auth keyring rows.
    keyring = SqlAlchemyAuthKeyStore(relational, env=settings.environment.value)
    # #889: boot opens or generates the signing key; a re-wrap counts it, an enrolment may trial it.
    keys = SqlAlchemyExportKeyStore(relational, env=settings.environment.value, audit_row=audit_row)

    def loop_store(
        connections: int,
    ) -> tuple[SqlAlchemyCredentialStore, Callable[[], Awaitable[None]]]:
        # #913 L1d (Q10): the order lane's credential reads, over a small lazy pool of their own,
        # which M2 alone builds on the lane's loop, holds, and frees once its signing closes. The
        # DSN is unwrapped here, at the call: the closure keeps `settings`, never the plaintext.
        dsn = settings.pg_dsn.get_secret_value()
        pool = SqlAlchemyRelationalRepository(
            dsn, "oms-secrets", pool_size=connections, max_overflow=0
        )
        return SqlAlchemyCredentialStore(pool), pool.dispose

    return build_secrets_service(
        store, store, audit, auth_keys=keyring, export_keys=keys, loop_store=loop_store
    )


def _record_factory(model: Any) -> Callable[..., Any]:
    return lambda **fields: model.model_validate(fields)


def build_app_context(
    settings: Settings | None = None,
    *,
    auth_clock: Callable[[], datetime] | None = None,
    secrets_bundle: SecretsBundle | None = None,
    account_fixture: AccountFixture | None = None,
    audit: AuditHandle | None = None,
) -> AppContext:
    """Construct an `AppContext` with real scaffold modules, no I/O performed.

    Every field is a live instance of its module's scaffold `service.py` —
    constructing them does no network/DB work (each `__init__` only sets
    `_started = False`), which is what keeps `create_app()` fast and
    fake-only per the acceptance criteria.

    #2893 S4: `account_fixture` is `create_app()`'s handle from `build_account_fixture`, None
    unless `CV_ACCOUNT_FIXTURE` is set; its REST transport becomes the exchange adapter's account
    REST transport, and (#836 slice 2b5) its private-socket connector the adapter's private-WS
    connector. None keeps httpx's own transport and production's connector.

    `audit` is M19 (built here when `None`); `create_app()` passes the one M2's sink writes
    through, holding the bundle's candidate capability for key import (#836).
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
    audit = _build_audit(resolved) if audit is None else audit
    secrets = secrets_bundle or _build_secrets(resolved, audit)
    return AppContext(
        settings=resolved,
        metrics=CollectorRegistry(),
        secrets=secrets.lifecycle,
        exchange_base=ExchangeBaseService(),
        exchange_bybit=ExchangeBybitService(
            credentials=secrets.exchange_borrower,
            rest_transport=None if account_fixture is None else account_fixture.rest_transport,
            private_ws_connect=(
                None if account_fixture is None else account_fixture.private_ws_connect
            ),
            environment=resolved.environment.value,
        ),
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
        admin=AdminService(secrets=secrets.metadata, signing_keys=secrets.signing_key_rotator),
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

#: What a module's stop may raise that `Supervisor._stop_each` never swallows (#3361): a
#: cancellation of the task running it, and the two exceptions that end the process.
_STOP_PROPAGATES: tuple[type[BaseException], ...] = (
    asyncio.CancelledError,
    KeyboardInterrupt,
    SystemExit,
)


def _stop_propagates(exc: BaseException) -> bool:
    """One of `_STOP_PROPAGATES`, alone or anywhere inside an exception group."""
    if isinstance(exc, BaseExceptionGroup):
        return exc.subgroup(_STOP_PROPAGATES) is not None
    return isinstance(exc, _STOP_PROPAGATES)


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

    async def stop_all(self, grace_s: float = TEARDOWN_BUDGET_S) -> None:
        """Stop every module in reverse start order. The default grace is the teardown term of
        the container stop budget (`Settings.api_stop_budget_s`, #2565). An outer
        `asyncio.timeout` or `wait_for` around it no longer cuts the teardown short (#3361): the
        cancellation it causes is re-raised only after the remaining stops, each within its own
        bound."""
        await self._stop_each(reversed(_SUPERVISOR_ORDER), grace_s)

    async def _stop_each(self, names: Iterable[str], grace_s: float) -> None:
        """Stop every module, isolated and bounded: one raising or hanging `stop()` never
        prevents a later one (e.g. `secrets.stop()` zeroing the KEK, C-2.7/C-12.2) from running.

        #3361: that holds whatever a stop raises, so no exception type skips the KEK zeroing.
        Each one is logged as the module's failed stop. A `BaseException` that is not an
        `Exception` (a library's own subclass, `GeneratorExit`, a task group's
        `BaseExceptionGroup`) goes no further, like an `Exception`. One of `_STOP_PROPAGATES`,
        alone or in a group, is never swallowed: the first is re-raised, unchanged, once the last
        stop has run. The later stops keep their own bounds, so a cancellation never makes the
        teardown longer than it would have been, and never ends it before the KEK zeroing;
        `start_all` and the lifespan likewise finish their stops before they re-raise. Each
        bound is cooperative: see `Settings._refuse_unfittable_stop_budget`.

        The failed-stop log line carries the exception's type (`exc_type`, #3403), so a
        cancellation or an exit request passing through a stop is not read as its own failure."""
        propagate: BaseException | None = None
        for name in names:
            try:
                async with asyncio.timeout(grace_s + STOP_SLACK_S):
                    await getattr(self._ctx, name).stop(grace_s)
            except BaseException as exc:  # incl. TimeoutError, the bound's cut
                structlog.get_logger("candleviewer.app").exception(
                    "supervisor: module stop failed", module=name, exc_type=type(exc).__name__
                )
                if propagate is None and _stop_propagates(exc):
                    propagate = exc
        if propagate is not None:
            raise propagate


def _hub_publisher(hub: RevocationHub) -> Callable[[str, str], Awaitable[None]]:
    """The auth module's revocation sink (#2272): close every socket of a revoked
    session. The revoke reason is internal; the client gets the §9.5 closed set:
    `user_disabled` for the SR-029 disable cascade, `session_revoked` otherwise."""

    async def _publish(session_id: str, reason: str) -> None:
        bye = "user_disabled" if reason == "user_disabled" else "session_revoked"
        await hub.revoke(session_id, bye)

    return _publish


@lru_cache(maxsize=1)
def _cached_spec() -> dict[str, Any]:
    """The packaged contract subset (#2555: the image ships no `docs/plan`); parsed once."""
    return load_contract_subset()


async def _deny_all_snapshot(user_id: uuid.UUID) -> PrincipalSnapshot:
    """The fake backend's WS principal: it has no identity store, so nothing is permitted."""
    return PrincipalSnapshot(user_id, frozenset(), frozenset())


def _now_ms() -> int:
    return int(time.time() * 1000)


def _session_authenticator(ctx: AppContext, refusals: EnrolmentRefusals) -> Authenticate:
    """Opaque bearer token -> (session_id, user_id, token expiry) via the session
    service. The expiry is the first instant the service refuses the token on
    time grounds; the gateway ends the socket's identity there (#2259). Raises
    (fail closed) while no session repository is wired.

    #2295: only a full session is served. An enrolment-only one is refused with `AuthRefused`
    (`bye mfa_enrollment_required`, 4403), counted and audited through *refusals*, with the
    source address the gateway supplies, as the HTTP guard's 403 is. One not minted as such
    (overlong, Q7, or it proved a second factor), any other verdict (deny by default, C-12.4)
    and a classification that fails raise like any failed `auth` (as an expired token does,
    `23-ws-protocol.md` §4.3), so HTTP (401) and the socket (`auth_failed`) both lead to a new
    sign-in; one past its expiry fails the lookup first. A user disabled or deleted since
    `require_active` read the session (`USER_INACTIVE`, a race with the disable) is refused as
    the gateway refuses a late registration (`bye user_disabled`, 4403, #3413), and counted as
    it is, its line naming the session and the user: #2911's refusal, not an enrolment one."""

    async def _authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
        record = await ctx.auth.sessions.authenticate_access_token(token)
        if ctx.auth.enrolment_gate_is_active:
            await _refuse_unless_full(record)
        return str(record.id), record.user_id, access_token_expires_at(record)

    async def _refuse_unless_full(record: SessionRecord) -> None:
        try:
            verdict = await ctx.auth.classify(record)
        except Exception as exc:
            refusals.unclassified(exc, channel="ws", method="GET", path=WS_PATH, record=record)
            raise
        if verdict is SessionClass.FULL:
            return
        if verdict is SessionClass.ENROLMENT_ONLY:

            async def _audit(ip: str | None) -> None:
                await refusals.refused(record, channel="ws", method="GET", path=WS_PATH, ip=ip)

            raise AuthRefused("mfa_enrollment_required", audit=_audit)
        if verdict is SessionClass.USER_INACTIVE:  # disabled or gone since the lookup (#2911)
            ids = {"session_id": str(record.id), "user_id": str(record.user_id)}
            raise AuthRefused("user_disabled", ids=ids)  # as a late registration is (#3413)
        refusals.expired(record, channel="ws", method="GET", path=WS_PATH)
        raise PermissionError("not a live enrolment-only session")

    return _authenticate


SnapshotLoader = Callable[[uuid.UUID], Awaitable[PrincipalSnapshot]]


def build_ws_principal_loader(
    settings: Settings, identity: SqlAlchemyIdentityProvider | None
) -> SnapshotLoader:
    """#2505: the WS principal on the real backend is the store's (`StorePrincipalLoader`):
    roles, permission codes and account grants, re-read at every `auth` and re-evaluation.
    The fake backend has no identity store, so its sockets keep the deny-all snapshot."""
    if settings.storage_backend != "real" or identity is None:
        return _deny_all_snapshot
    return StorePrincipalLoader(
        identity,
        SqlAlchemyScopeSource(
            SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "ws-principal")
        ),
    )


async def gateway_overloaded_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Map a refused statechart inbox (E50-T15, CV-C33), or a command a degraded machine's
    admission refused (E50-T63, `GatewayDegradedError`), to RFC 7807 HTTP 503."""
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


async def audit_test_clock_boot(ctx: AppContext) -> None:
    """#2728: the lifespan writes the test clock's boot audit record before the app serves. The
    fake backend has no audit store, so there the boot warning is the only record."""
    if ctx.settings.test_clock and ctx.audit.is_active:
        await audit_test_clock_enabled(ctx.settings, _LazyAuditEmitter(ctx.audit))


class _StampedApp(FastAPI):
    """#966 BK-11: the whole ASGI stack inside `NoStoreNoReferrer`, outside every user middleware
    and Starlette's own error middleware, so every answer to the backup fetch's path (its token
    is a credential) is no-store and no-referrer, the guards' refusals and a `500` included. The
    pinned order of the user middleware (#2421, #2295) is untouched. `NoSniff` (#3990) is the
    outermost layer: `X-Content-Type-Options: nosniff` on every HTTP answer, a `500` included."""

    def build_middleware_stack(self) -> ASGIApp:
        return NoSniff(NoStoreNoReferrer(super().build_middleware_stack()))


def create_app(
    settings: Settings | None = None,
    *,
    snapshot_loader: SnapshotLoader | None = None,
    user_role_store: UserRoleStore | None = None,
    account_access_store: AccountAccessStore | None = None,
    user_disable: UserDisable | None = None,
    principal_resolver: SnapshotResolver | None = None,
    ws_authenticate: Authenticate | None = None,
    auth_clock: Callable[[], datetime] | None = None,
    onboarding_store: Any = None,
    bars_now_us: Callable[[], int] | None = None,
    secrets_bundle: SecretsBundle | None = None,
    audit_verify_runner: AuditVerifyRunner | None = None,
    hmac_keys: HmacKeys | None = None,
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
    # #2086: the keyless-testnet server test clock; None (real UTC) unless CV_TEST_CLOCK is on.
    auth_clock = auth_clock or build_test_clock(resolved)
    # #2893: the dev-only account fixture transport; None unless CV_ACCOUNT_FIXTURE is set. A build
    # without the dev package refuses boot here, before any module is built. S4 hands its REST
    # transport to the exchange adapter; the handle stays on `app.state` for the private socket.
    account_fixture = build_account_fixture(resolved)
    spec = _cached_spec()
    # #2097: the auth perf switch; refused outside a keyless testnet before anything is built.
    auth_perf = auth_perf_enabled(resolved)
    app = _StampedApp(
        title="CandleViewer API",
        version=resolved.version,
        dependencies=[Depends(make_deny_undeclared_dependency(declared_operations(spec)))],
    )
    app.add_exception_handler(GatewayOverloadedError, gateway_overloaded_handler)
    app.add_exception_handler(GatewayDegradedError, gateway_overloaded_handler)  # E50-T63
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    app.add_exception_handler(ViewAsUnstamped, view_as_unstamped_handler)  # #3085 S8: 503
    install_error_redaction(app)  # E43-T06: no secret echo via 422/500 bodies
    audit = _build_audit(resolved)
    bundle = secrets_bundle or _build_secrets(resolved, audit)
    ctx = build_app_context(
        resolved,
        auth_clock=auth_clock,
        secrets_bundle=bundle,
        account_fixture=account_fixture,
        audit=audit,
    )
    app.state.app_context = ctx
    app.state.account_fixture = account_fixture
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
    # E17-T08: the gateway's one hub and the `machines.{entity}.state` registry come first, so each
    # module that owns a machine is handed the one feed it publishes through (23 §6.4). The timers
    # are the running loop's, and `WsRuntime` closes them.
    ws_sequencing = SequencingHub()
    machine_states = MachineStateRegistry(
        hub=ws_sequencing, call_later=loop_call_later, wall_ms=_now_ms
    )
    machine_feed = RegistryFeed(
        machine_states, environment=resolved.environment.value, now_ms=_now_ms
    )
    app.state.machine_feed = machine_feed
    ctx.auth.attach_machine_feed(machine_feed)
    # E16-T07 (#491): DiskBudget on the real backend (no recorder flag; lifespan-started).
    app.state.disk_budget = build_disk_budget(
        resolved,
        bus=ctx.bus.bus,
        recorder_repo=SqlAlchemyRecorderRepository(_kb_pg) if _kb_pg is not None else None,
    )
    app.state.kline_boundary_refresh = KlineBoundaryRefreshTask(
        kline_boundary,
        kline_policy_loader(SqlAlchemyRecorderRepository(_kb_pg) if _kb_pg is not None else None),
        float(resolved.kline_boundary_refresh_s),
    )
    # #2599: the public WS and the instrument catalogue share one public REST client (C-12.7).
    public_rest = PublicRest(ctx) if resolved.ingestion_ws_enabled else None
    if public_rest is not None:
        wire_public_ws(ctx, kline_boundary, public_rest, machine_feed)
    # E12 #2031 (flag `bars_enabled`, default off - C-4.13; removal with #398/#399): the set
    # and its writer are started/stopped by the lifespan (set first, then writer).
    # #399: the WS series store (hydrated by the reader, built first) and the bars publisher on
    # the gateway's one hub (the machine states above share it), both on the emit path.
    bars_reader: BarReader | None = None
    bars_series: SeriesStore | None = None
    indicators: IndicatorEngine | None = None
    snapshot_adapters: dict[str, SnapshotSource] = {}
    if resolved.bars_enabled:
        bars_sink = _build_bars_sink(resolved)
        bars_clock = bars_now_us or (lambda: time.time_ns() // 1000)
        # #2787 D2-G2 (D-G2 = A): the store's reads on their own connection, closed after the
        # sink; REST bars, klines and the writer keep the sink's (20-architecture.md §4.2).
        hydrate_wire: LazyPgWire | None = None
        hydrate_reader: BarReader | None = None
        if bars_sink is not None:
            bars_reader = BarReader(bars_sink.pgwire, _no_rebuild_executor, now_us=bars_clock)
            hydrate_wire = bars_sink.pgwire.sibling("bars_hydrate")
            hydrate_reader = BarReader(hydrate_wire, _no_rebuild_executor, now_us=bars_clock)
        bars_series = SeriesStore(hydrate_reader.read_tail if hydrate_reader is not None else None)
        scales = functools.partial(_catalogue_scales, ctx)
        publisher = BarsPublisher(ws_sequencing, scales, swap_reason="generation_swap")
        # E13-T02 (#426): the indicator engine, on the emit path after the publisher; it primes
        # from the store, and reads older bars through the store's own reader, so its reads join
        # the first reads on `bars_hydrate`, never REST's connection (D-G2, 20 §4.2).
        history = StoredHistory(hydrate_reader) if hydrate_reader is not None else None
        indicators = IndicatorEngine(bars_series, history=history, now_us=bars_clock)
        indicators.listen(IndicatorsPublisher(ws_sequencing))
        # #2787 D2-H1, 23 §7.4: a repairing read reaches the subscribers through the store's hook
        # alone, never a task that diffs `latest()` across an await (it can miss a repair).
        bars_series.on_repair(_repair_hooks(publisher.history_repair, indicators.history_repair))
        app.state.bars_runtime = wire_bars(
            ctx,
            inner_sink=bars_sink,
            sink_stop=bars_sink.stop if bars_sink is not None else None,
            sink_degraded=(lambda: bars_sink.pgwire.degraded) if bars_sink is not None else None,
            reader_stop=hydrate_wire.close if hydrate_wire is not None else None,
            now_us=bars_clock,
            tick_size=lambda sym: _catalogue_tick_size(ctx, sym),
            series=bars_series,
            publisher=publisher,
            indicators=indicators,
        )
        snapshot_adapters["bars"] = BarsSnapshotSource(
            bars_series, scales, seed=publisher.note_generation,
            stale=app.state.bars_runtime.builder_set.quarantined,
        )  # fmt: skip
        snapshot_adapters["indicators"] = IndicatorsSnapshotSource(
            indicators, stale=app.state.bars_runtime.builder_set.quarantined
        )
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
            accounts_health=ctx.accounts.health,
            # #3874: the real tiers' probes; the fake backend's tiers are not checked
            storage_health=ctx.storage.tier_health if resolved.storage_backend == "real" else None,
            # #913 slice 3E: the OMS runtime's state while it runs (real backend only)
            oms_state=lambda: _oms_state(getattr(app.state, "oms_runtime", None)),
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
    health_publisher = HealthSystemPublisher(clock_guard=lambda: ctx.ingestion.clock)
    health_registry = HealthRegistry(
        events=(
            PgSystemEventWriter(health_pg, redact_details=system_event_redactor())
            if health_pg is not None
            else None
        ),
        on_snapshot=health_publisher,
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
    app.include_router(make_health_report_router())
    csrf_codec = build_csrf_codec(resolved)
    app.state.csrf_codec = csrf_codec
    # In-flight CSRF-refusal audits; drained (bounded) at shutdown before audit stops.
    csrf_audits = RefusalAuditTracker()
    app.state.csrf_refusal_audits = csrf_audits
    # #2295: refusals of an enrolment-only session, HTTP and WS, share that cap and drain.
    enrolment_refusals = EnrolmentRefusals(_LazyAuditEmitter(ctx.audit), tracker=csrf_audits)
    app.include_router(
        make_auth_router(
            ctx.auth, ctx.audit, identity=identity, csrf=csrf_codec, server_timing=auth_perf
        )
    )
    # E09-S03: session routes; revocation is pushed to sockets via the hub
    # (4401). Identity provider is E09-T03, so refresh/session return 501 and
    # every route answers 503 until a session repository is wired.
    revocation_hub = RevocationHub(remember_s=ACCESS_TOKEN_TTL.total_seconds())
    app.state.revocation_hub = revocation_hub
    ctx.auth.attach_revocation_sink(_hub_publisher(revocation_hub))  # every revoke path (#2272)
    # The backstop's audit record (C-2.9, #3120), from `require_active` or a refused `refresh()`
    # (#3331), in flight under the shared cap, through the audit lane's façade (ADR-0037), the
    # writer its fallback.
    ctx.auth.attach_backstop_audit(
        SessionBackstopAudit(_LazyLaneEmitter(ctx.audit), tracker=csrf_audits)
    )
    app.include_router(
        make_session_router(
            ctx.auth,
            ctx.audit,
            identity=identity,
            allowed_origins=resolved.allowed_origin_set,
            csrf=csrf_codec,
            audit_tracker=csrf_audits,  # one in-flight cap + shutdown drain for refusal audits
            enrolment_refusals=enrolment_refusals,  # unlock answers as the guard does (#2295)
            # #2300: unlock records on B16 and checks the password on login's path (step-up).
            unlock_authority=lambda: ctx.auth.step_up if ctx.auth.step_up_is_active else None,
        )
    )
    # #3085: the viewer reads and ends its own session's view-as context. The service is read per
    # request (built below; `None` on the fake backend, where both answer 503 after
    # authenticating), and the target's names come from the identity provider's narrow read.
    app.include_router(
        make_view_as_router(
            ctx.auth,
            views=lambda: app.state.view_as,
            names=identity,
            clock=auth_clock or (lambda: datetime.now(UTC)),
        )
    )
    # #2713: the shell bootstrap (`/me`, `/me/preferences`, `/me/keymap`), self only. Without an
    # identity provider (fake backend) it answers 503/501 after authenticating, never unchecked.
    app.include_router(
        make_me_router(
            ctx.auth, identity=identity, environment=resolved.environment, clock=auth_clock
        )
    )
    # QA #1648 d1: live WS gateway. Role changes (`PUT /users/{id}/roles`)
    # notify the registry, which pushes `permission_change` and revokes
    # now-forbidden subscriptions. The principal is read from the store on
    # the real backend and is deny-all on the fake one (#2505).
    # #377 wiring: E08 upstream sink, BarBuilderSet leases, audit, instrument check, snapshots
    # (bars #2195, book #2196; stubs until #2197), sequencing; lifecycle + shutdown in `WsRuntime`.
    ws_upstream = UpstreamRefs(IngestionUpstreamSink(ingestion_streams(ctx)))
    # E27-T04 (#837): the accounts module's `wallet` topic. Its snapshots read the account health
    # runtime built below, which attaches to it, and its deltas go out through this hub.
    ws_wallet = wallet_topic(ws_sequencing)
    snapshot_adapters["wallet"] = ws_wallet
    # E40-T04: the alerts module's `alerts` topic. The deliveries reader is attached below, with
    # the alerts store; its deltas come from the dispatcher and the inbox routes (`on_change`).
    ws_alerts = alerts_topic(ws_sequencing)
    snapshot_adapters["alerts"] = ws_alerts
    # E16-T08 (#492): the recorder module's `recorder` topic; the recording status attaches below.
    ws_recorder = recorder_topic(ws_sequencing)
    snapshot_adapters["recorder"] = ws_recorder
    # E17-T08: `sub` is authorised and snapped from `machine_states`, built above with the feed.
    ws_services = SubscriptionServices(
        upstream=ws_upstream,
        bars=getattr(getattr(app.state, "bars_runtime", None), "builder_set", None),
        audit=_LazyAuditEmitter(ctx.audit),
        instrument_known=lambda sym: _ws_symbol_known(ctx, sym),
        qty_step=lambda sym: _catalogue_qty_step(ctx, sym),
        series=bars_series,
        indicators=indicators,
        snapshots=default_snapshot_router(
            {"machines": machine_states, "book": book_snapshot_source(ctx), **snapshot_adapters}
        ),
        sequencing=ws_sequencing,
        bars_off=not resolved.bars_enabled,
        machines=machine_states,
        # E17-T06: a span id (`sp`, 23 §3.1) on each sampled frame while latency telemetry is on.
        span_ids=new_span_id if resolved.telemetry_enabled else None,
    )
    ws_registry = ConnectionRegistry(
        snapshot_loader or build_ws_principal_loader(resolved, identity),
        _now_ms,
        services=ws_services,
        # #3413: a disable is remembered for one access-token lifetime, and a token is dated by
        # the same lifetime; the registry refuses a memory shorter than it.
        disabled_memory_s=ACCESS_TOKEN_TTL.total_seconds(),
        access_token_ttl_s=ACCESS_TOKEN_TTL.total_seconds(),
    )
    machine_states.on_revoked = MachineRevocationAudit(ws_registry)  # its `evicted` rows (§6.4)
    ws_hub = GatewayHub(
        max_per_user=resolved.ws_max_connections_per_user,
        max_auths_per_min=resolved.ws_max_auths_per_user_per_min,
    )
    kill_switch = KillSwitchView()
    app.state.ws_registry = ws_registry
    app.state.ws_hub = ws_hub
    app.state.ws_events = ws_events = WsEvents(ws_registry, ws_hub, kill_switch)
    app.state.ws_runtime = WsRuntime(ws_hub, ws_upstream, resolved, machines=machine_states)
    # E17-T03 (#412, C-4.13): the budgeted outbound pipeline, off by default. Without a config
    # the gateway keeps its 1 024-frame push bound: the flag swaps the bound, never removes it.
    ws_backpressure = (
        BackpressureConfig.from_settings(resolved) if resolved.ws_backpressure_enabled else None
    )
    include_ws_router(  # #3907: `/ws` and, under the server base, `/api/v1/ws`
        app,
        make_ws_router(
            authenticate=ws_authenticate or _session_authenticator(ctx, enrolment_refusals),
            registry=ws_registry,
            revocation_hub=revocation_hub,
            allowed_origins=resolved.allowed_origin_set,  # SR-042/SR-183 upgrade check (#2239)
            hub=ws_hub,
            audit=_LazyAuditEmitter(ctx.audit),
            # #2269: refused upgrades share the REST refusal audits' in-flight cap and drain.
            origin_audit=OriginRefusalAudit(_LazyAuditEmitter(ctx.audit), tracker=csrf_audits),
            auth_timeout_s=resolved.ws_auth_timeout_s,
            max_frame_bytes=resolved.ws_max_inbound_frame_bytes,
            server_version=resolved.version,
            git_sha=resolved.git_sha,
            kill_switch=kill_switch.snapshot,
            # After a first `auth_ok`: the read-only gate, then an unresolved break-glass (O4).
            system_notices=lambda: _gate_notices(ctx) + ctx.auth.break_glass_notice.notices(),
            # §15.9 (E42-T03): a Manager or Viewer learns a flag key only as the registry's
            # `visibility` admits; a key the registry does not define reaches the Owner alone.
            flag_visible=default_registry().visible_to,
            # §15.9 (#4517): the snapshot at `auth_ok`, from the flag service built below (read per
            # call: `start()` may rebuild it), resolved for the user as the REST list resolves it.
            flag_snapshot=lambda user, roles: feature_flags_snapshot(
                app.state.feature_flags.service, user, roles
            ),
            backpressure=ws_backpressure,
            # §9.6 (#3085): an `auth` reads its session's view-as binding through the service
            # built below, read per call as S7's guard reads it, so a missing one fails the
            # `auth`; none on the fake backend, which binds no session.
            view_as=(
                SessionViewAs(
                    lambda: app.state.view_as,
                    ctx.auth.view_as_store,
                    clock=auth_clock or (lambda: datetime.now(UTC)),
                )
                if ctx.auth.view_as_store_is_active
                else None
            ),
            # §9.6: a viewing session's refused action frame is recorded by the recorder built
            # below, read per call as S7's guard reads it, so a missing one fails the refusal's
            # record; none on the fake backend, which has no identity to label it.
            view_as_refusals=(
                SessionViewAsRefusals(
                    lambda: app.state.view_as_refusals,
                    IdentityLabels(identity),
                )
                if identity is not None
                else None
            ),
        ),
    )
    # E27-T02: gate transitions (KEK latch, mesh trip) reach connected clients directly.
    ctx.mesh_system_topic_publisher.direct_sinks.append(ws_hub.broadcast_system)
    health_publisher.direct_sinks.append(ws_hub.broadcast_system)  # E42-T05: health frames
    # #2492: unless a test injects them, the owner user-management routes (role change,
    # invites, owner TOTP reset) get the session-backed snapshot resolver and the Postgres
    # role store; the E09-S06 onboarding checklist gets the same resolver (#2506). The fake
    # backend has no identity, role store or onboarding store to authorise against, so they
    # stay `None` there and those routes fail closed with 501 (never unchecked).
    owner_resolver: SnapshotResolver | None = principal_resolver
    if owner_resolver is None and identity is not None:
        owner_resolver = SessionSnapshotResolver(lambda: ctx.auth.sessions, identity)
    if user_role_store is None:
        user_role_store = build_user_role_store(resolved)
    if account_access_store is None:
        account_access_store = build_account_access_store(resolved, ctx.audit)
    # #2648 S9c: grant writes and their pushes (drained at shutdown, main.py); positions unknown.
    access_service: AccountAccessService | None = None
    if account_access_store is not None:
        notifier, positions = app.state.ws_events, _NoPositionStore()
        access_service = AccountAccessService(account_access_store, notifier, positions=positions)
    app.state.account_access_service = access_service
    # E42-T04 S6 (#965): `DELETE /users/{userId}` (None on the fake backend: 501). `rule_store` is
    # the one `ctx.rules` binds below; the lifespan drains `app.state.user_disable` before it stops.
    rule_store = PostgresRuleStore(
        SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "rules")
    )
    if user_disable is None:
        user_disable = build_user_disable_service(
            resolved,
            auth=ctx.auth,
            rules=ctx.rules,
            rule_store=rule_store,
            audit=_LazyAuditEmitter(ctx.audit),
            positions=_NoPositionStore(),
            publish_revocation=_hub_publisher(revocation_hub),
            close_user_sockets=ws_events.user_disabled,  # every socket of the user (S7)
            clock=auth_clock,
        )
    app.state.user_disable = user_disable
    # E42-T10 (#2650): the anonymisation reaper, which the lifespan starts whatever retention says,
    # and the door `?purge=true` schedules through while it runs; `None` on the fake backend, where
    # `?purge=true` answers `503 purge_unavailable`.
    users_purge = build_users_purge_task(
        resolved,
        auth=ctx.auth,
        audit=_LazyAuditEmitter(ctx.audit),
        publish_revocation=_hub_publisher(revocation_hub),
        clock=auth_clock,
    )
    app.state.users_purge_task = users_purge
    # E42-T03: the feature-flag runtime (store, service, writer, push, maintenance); its maintenance
    # gate is the first check of the shared order-entry gate composed below; the lifespan starts it.
    feature_flags = build_feature_flags(
        resolved,
        audit=_LazyAuditEmitter(ctx.audit),
        step_up=step_up_port(ctx.auth, restate_flag_write, _LazyAuditEmitter(ctx.audit)),
        hub=ws_hub,
        users=user_role_store,
    )
    app.state.feature_flags = feature_flags
    app.state.flag_metrics = export_flag_metrics(ctx.metrics, env=resolved.environment.value)
    # E09-S04: step-up, owner TOTP reset and the read-only write guard.
    app.include_router(
        make_step_up_router(
            ctx.auth,
            _LazyAuditEmitter(ctx.audit),
            principal_resolver=owner_resolver,
            positions=_NoPositionStore(),
            users=user_role_store,
            audit_ready=_audit_ready(ctx.audit),
        )
    )
    # B16 audit actions write through the M19 emitter (PR #1674 finding 3).
    set_b16_audit_sink(_LazyAuditEmitter(ctx.audit))
    app.middleware("http")(make_read_only_guard(ctx.auth, _LazyAuditEmitter(ctx.audit)))
    # #3085: the view-as guard, added after (so outside) the read-only/step-up guard, so a refused
    # write is never a step-up challenge and binds no key, and before the enrolment-only guard,
    # so CSRF, the idle lock and the enrolment check come first. It reads the view-as service
    # (`None` on the fake backend) and the refusal recorder per request; both are set below, so a
    # missing one fails loudly. The protective writes' handlers register on
    # `app.state.protective_writes` as they are mounted. For a live protective write it also
    # checks the target's permission with `permissions` (the contract's `x-rbac`), `identity` (the
    # target's reads) and `denials` (the `rbac.denied` record of a refusal): without the first two
    # such a write is a 503, and `permissions` given without `denials` is not built.
    protective_writes = ProtectiveWrites(declared_operations(spec))
    app.state.protective_writes = protective_writes
    app.middleware("http")(
        make_view_as_guard(
            ctx.auth,
            views=lambda: app.state.view_as,
            refusals=lambda: app.state.view_as_refusals,
            protective=protective_writes,
            operations=declared_operations(spec),
            clock=auth_clock or (lambda: datetime.now(UTC)),
            permissions=rbac_permissions(spec),
            identity=identity,
            denials=_LazyAuditEmitter(ctx.audit),
        )
    )
    # #2295: the enrolment-only session reaches five operations; added after (so outside) the
    # read-only/step-up guard, so a refused request never records a step-up challenge, and
    # before the idle-lock gate, so a locked session meets the lock first.
    app.middleware("http")(
        make_enrolment_only_guard(
            ctx.auth,
            refusals=enrolment_refusals,
            operations=declared_operations(spec),
            sessionless=sessionless_operations(spec),
        )
    )
    # #2300: an idle-locked session gets `401 session_idle_locked` from every route but the
    # three allowed while locked. Added after the read-only guard and before the CORS layer and
    # `CsrfMiddleware`, so it runs inside both and outside every route-level guard.
    app.add_middleware(
        IdleLockMiddleware,
        sessions=lambda: ctx.auth.sessions if ctx.auth.sessions_is_active else None,
        spec=spec,
    )
    # #3085: the view-as service and its sweeper, which the lifespan runs (`None` on the fake
    # backend, which has no session store). A role change, by either users router, ends the
    # contexts it makes ineligible before the WS registry re-evaluates the user's sockets.
    view_as = build_view_as(
        resolved,
        auth=ctx.auth,
        identity=identity,
        audit=_LazyAuditEmitter(ctx.audit),
        runner=csrf_audits,  # one in-flight cap and shutdown drain for the end records
        hub=revocation_hub,  # an end closes the sockets bound to its context
        clock=auth_clock,
    )
    app.state.view_as, app.state.view_as_sweeper = view_as or (None, None)
    roles_notifier: PermissionChangeNotifier = (
        ws_registry if view_as is None else RoleChangeNotifier(view_as[0], ws_registry)
    )
    # Audit emitter + notifier are mandatory; store/resolver `None` -> 501.
    app.include_router(
        make_users_router(
            user_role_store,
            _LazyAuditEmitter(ctx.audit),
            owner_resolver,
            roles_notifier,
            auth=ctx.auth,
            account_access=account_access_store,
            access_service=access_service,
            user_disable=user_disable,
            user_purge=users_purge,
        )
    )
    app.include_router(
        make_invites_router(
            ctx.auth,
            _LazyAuditEmitter(ctx.audit),
            owner_resolver,
            audit_ready=_audit_ready(ctx.audit),
        )
    )
    # E42-T09 (#2649): `GET`/`PATCH /users/{userId}` and the admin view of a user's sessions; a
    # PATCH to `disabled` runs `user_disable`'s cascade. No store (fake backend): 501 after RBAC.
    # After the invites router: `GET /users/invites` must match before `GET /users/{userId}`.
    app.include_router(
        make_user_admin_router(
            build_user_admin_store(resolved),
            _LazyAuditEmitter(ctx.audit),
            owner_resolver,
            roles_notifier,
            auth=ctx.auth,
            user_disable=user_disable,
        )
    )
    # #2266 D2: `rewrapKek`, the KEK re-wrap entry point. Owner only; the handler demands step-up
    # `keys` after RBAC (#2304 slice 3b); M2 runs it behind `AdminService` (counts only).
    keys_elevation = request_elevation(ctx.auth, "keys")
    app.include_router(
        make_admin_kek_router(
            ctx.admin,
            _LazyAuditEmitter(ctx.audit),
            owner_resolver,
            auth=ctx.auth,
            elevation=keys_elevation,
        )
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
    # #3085: `admin.view_as_refused` records under the viewers' own cap, never a slot of the
    # budget above, whose other settings they share. The view-as guard, the sockets and the start
    # call it; the lifespan runs its flush task as it runs the one above.
    view_as_refusals = ViewAsRefusalRecorder(
        _LazyAuditEmitter(ctx.audit),
        operations=declared_operations(spec),
        per_hour=resolved.view_as_refusal_budget_per_hour,
        tracked_users=resolved.audit_budget_tracked_users,
        inflight_cap=resolved.audit_inflight_writes,
        flush_seconds=resolved.audit_read_flush_seconds,
    )
    app.state.view_as_refusals = view_as_refusals
    app.state.view_as_refusal_flush = view_as_refusals.flush
    # #3085: the Owner starts a view-as context (`startViewAs`) behind the admin-area guard
    # (`users:write`); its refusals before the step-up gate are recorded within the viewers' cap.
    # The service and the recorder are read per request; without them (fake backend) it is a 503.
    app.include_router(
        make_view_as_start_router(
            ctx.auth,
            resolver=audit_resolver,
            audit=_LazyAuditEmitter(ctx.audit),
            views=lambda: app.state.view_as,
            refusals=lambda: app.state.view_as_refusals,
            users=identity,
            clock=auth_clock or (lambda: datetime.now(UTC)),
        )
    )
    # A chain break also raises a critical system event, as the recorder's job does: from the
    # on-demand route and from the scheduled verify run (#2966).
    chain_break_events = (
        PgSystemEventWriter(health_pg, redact_details=system_event_redactor())
        if health_pg is not None
        else None
    )
    admin_jobs = AdminJobStore()
    app.state.admin_jobs = admin_jobs  # cancelled by the lifespan at shutdown
    # #889 S9: the export files the download serves, found in the job store it shares; the
    # lifespan probes and sweeps them. #889 S10: the export job, given M2's signer and key
    # directory (`audit`'s ports) alone, and M2's read of a running rotation for its own 409.
    export_signing = ExportSigning(
        signer=bundle.export_signer, keys=bundle.signing_keys,
        rotating=bundle.rotation_running.running, environment=resolved.environment,
        max_rows=resolved.audit_export_max_rows, max_bytes=resolved.audit_export_max_bytes,
    )  # fmt: skip
    audit_exports = AuditExports(
        admin_jobs, resolved.data_dir, ttl_s=resolved.audit_export_ttl_s, signing=export_signing
    )
    app.state.audit_exports = audit_exports
    # #889 S7: `rotateAuditSigningKey`. Owner only; the handler demands step-up `keys` after RBAC
    # (#2304 slice 3b); M2 rotates behind `AdminService`, never while an export job is queued or
    # running in this job store, and a `429` is counted under the audit budget. A refusal's
    # `rbac.denied` names the caller's session through `ctx.auth` (#4174).
    emitter = _LazyAuditEmitter(ctx.audit)
    rotations = make_audit_signing_router(
        ctx.admin, emitter, owner_resolver, budget=audit_budget, jobs=admin_jobs, auth=ctx.auth,
        elevation=keys_elevation,
    )  # fmt: skip
    app.include_router(rotations)
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
            verify_max_span=resolved.audit_verify_max_span,
            verify_limiter=AuditVerifyLimiter(
                rate_per_hour=resolved.audit_verify_rate_per_hour,
                tracked_users=resolved.audit_budget_tracked_users,
            ),
            verify_deadline_s=resolved.audit_verify_deadline_s,
            verify_events=chain_break_events,
            exports=audit_exports,
            step_up=ctx.auth,
            download_limiter=AuditVerifyLimiter(
                rate_per_hour=resolved.audit_download_rate_per_hour,
                tracked_users=resolved.audit_budget_tracked_users,
            ),
            # #889 S7: `listAuditSigningKeys` reads M2's directory, its `verified` marks M2's.
            signing_keys=bundle.signing_keys,
            export_limiter=AuditVerifyLimiter(
                rate_per_hour=resolved.audit_export_rate_per_hour,
                tracked_users=resolved.audit_budget_tracked_users,
            ),
            export_max_range_days=resolved.audit_export_max_range_days,
        )
    )
    app.include_router(make_hotkey_audit_router(_LazyAuditEmitter(ctx.audit), audit_resolver))
    if auth_perf:  # #2097: owner-only Argon2id params; never mounted with the switch off
        app.include_router(make_auth_perf_router(audit_resolver))
    # E04-T06: frontend telemetry push. One facade per process on ctx.metrics
    # (the lifespan's MetricsRuntime reuses it). Session-authenticated via the
    # same session resolver; `None` (fake backend) fails closed with 501.
    # Process collectors read /proc; the lifespan adds them (no I/O here).
    metrics_facade = Metrics(resolved.environment.value, registry=ctx.metrics)
    app.state.metrics_facade = metrics_facade
    # E50-T63: the statechart persistence bundle, on this one facade; `None` without HMAC keys
    # (no provider yet, #2701) or on the fake backend: persist and restore stay unwired. The
    # lifespan starts it before `start_all` and stops it after `stop_all`.
    persistence = build_statechart_persistence(
        resolved, hmac_keys=hmac_keys, metrics=metrics_facade
    )
    app.state.statechart_persistence = persistence
    _attach_replay_sessions(
        ctx, resolved, _kb_pg, coverage_service, feed=machine_feed, persistence=persistence
    )  # supervised
    # E08-T06: serve the declared ingestion/adapter series on the scraped
    # registry with consistent `env` + `exchange` labels (the venue name is
    # owned by the adapter, C-2.2).
    app.state.ingestion_metrics = export_ingestion_metrics(
        ctx.metrics, env=resolved.environment.value, exchange=ctx.exchange_bybit.venue
    )
    # E12-T03: bars series (builders + BarBuilderSet) on the scraped registry.
    app.state.bars_metrics = export_bars_metrics(ctx.metrics, env=resolved.environment.value)
    # E13-T02: the indicator engine's series (instances, recomputes, caps).
    app.state.indicator_metrics = export_indicator_metrics(
        ctx.metrics, env=resolved.environment.value
    )
    # E16-T03/T07: StreamWriter and DiskBudget series on the scraped registry.
    app.state.recorder_metrics = export_recorder_metrics(
        ctx.metrics, env=resolved.environment.value
    )
    app.state.secrets_metrics = export_secrets_metrics(ctx.metrics, env=resolved.environment.value)
    # #2496: the mesh-guard gauge, read by the `NetBindingUnsafe` page.
    app.state.net_metrics = export_net_metrics(ctx.metrics, env=resolved.environment.value)
    # E17-T02: CVWB encode frames/bytes per body_kind.
    app.state.cvwb_metrics = export_cvwb_metrics(ctx.metrics, env=resolved.environment.value)
    # #377: every `cv_ws_*` gateway series (lifecycle, subscriptions, sequencing).
    app.state.ws_metrics = export_ws_metrics(ctx.metrics, env=resolved.environment.value)
    # #2090: auth series (incl. auth_csrf_refused_total) on the scraped registry.
    app.state.auth_metrics = export_auth_metrics(ctx.metrics, env=resolved.environment.value)
    # E42-T02: audit page time by filter class, and reads over their time budget.
    app.state.audit_query_metrics = export_audit_query_metrics(
        ctx.metrics, env=resolved.environment.value
    )
    # ADR-0037 S4a (#3009): the audit lane's series and the writer's refusals by domain.
    app.state.audit_lane_metrics = export_audit_lane_metrics(
        ctx.metrics,
        env=resolved.environment.value,
        audit=ctx.audit,
    )
    # E42-T04 (#965 R7): user lifecycle calls and steps, read by the lifecycle tickets.
    app.state.user_lifecycle_metrics = export_user_lifecycle_metrics(
        ctx.metrics, env=resolved.environment.value
    )
    # E26-T02: replay read-path series (reads per stream and tier, gap markers, read-ahead).
    app.state.replay_metrics = export_replay_metrics(ctx.metrics, env=resolved.environment.value)
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
    # E14-T01: drawings metrics (batch/conflict recorded by the router) + 90-day soft-delete purge.
    app.state.drawings_metrics = DrawingsMetrics(
        batch_ops=metrics_facade.histogram(
            "cv_drawings_batch_ops",
            "Operations per POST /drawings/batch request.",
            buckets=(1, 5, 10, 25, 50, 100, 200),
        ),
        conflicts=metrics_facade.counter(
            "cv_drawings_conflicts_total",
            "Drawing write conflicts by rule.",
            ("rule",),
            max_series=4,
        ),
        purged=metrics_facade.counter(
            "cv_drawings_purged_total", "Soft-deleted drawings hard-purged after 90 days."
        ),
        rows=metrics_facade.gauge(
            "cv_drawings_rows", "Live drawings by tool.", ("tool",), max_series=len(TOOLS)
        ),
    )
    # `drawings` has no forbid-delete trigger, so the app DSN may purge.
    app.state.drawings_purge_task = DrawingsPurgeTask(
        SqlAlchemyDrawingRepository(
            SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "drawings-retention")
        ),
        _retention,
        app.state.drawings_metrics.purged,
        app.state.drawings_metrics.rows,
        TOOLS,
    )
    app.state.incidents_purge_task = _build_incidents_purge(resolved)
    # E09-S06: server-evaluated first-run checklist. Steps whose owning epic
    # has not shipped (E27 api_key/demo, E39 profile limits) have no probe and
    # render `pending` ("coming soon") via the flag table, never a client stub.
    app.include_router(
        _build_onboarding_router(
            resolved,
            ctx,
            owner_resolver,  # session-backed unless a test injects one (#2506)
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
    # #3998: the gauge of the runtime role's guarded privileges, set by `StorageService.start()`'s
    # check on the real backend (catalogue entry registered just above).
    ctx.storage.attach_privileges_gauge(metrics_facade.get("cv_db_guarded_privileges_held").child())
    # #2314: M13 row gauges (catalogue entries registered just above), refreshed by the
    # supervisor-started `AccountsService`. Fake backend: no store, so the gauges stay unset.
    accounts_counts = _build_accounts_counts(resolved)
    if accounts_counts is not None:
        ctx.accounts.attach_row_gauges(
            accounts_counts,
            metrics_facade.get("cv_accounts_rows"),
            metrics_facade.get("cv_api_keys_rows"),
            profile_rows=metrics_facade.get("cv_profile_rows"),
            env=resolved.environment.value,
        )
    # E27-T03 (#836): the stored-key boot assertion and hourly re-check, run by the supervisor-
    # started `AccountsService` before the app serves (real backend only).
    selfcheck = wire_key_selfcheck(ctx, _LazyAuditEmitter(ctx.audit), metrics_facade)
    # E27-T03 (#836): `createApiKey`; its flow holds M2's candidate capability (real backend only).
    # The lifespan drains its imports before `stop_all` stops audit and M2, then frees its pool.
    key_imports = wire_key_import(ctx, bundle.candidate_keys, _LazyAuditEmitter(ctx.audit))
    app.state.key_imports = key_imports
    app.include_router(
        make_exchange_keys_router(
            key_imports,
            _LazyAuditEmitter(ctx.audit),
            owner_resolver,
            egress_ip=resolved.egress_ip,
            rotation=KeyRotationPolicy.from_settings(resolved),
            # #836 slice 2b6: `testApiKey`, its verdict enforced by the self-check (decision 11).
            tests=wire_key_test(ctx, selfcheck, key_imports),
            auth=ctx.auth,  # a refusal names the caller's session (#4174)
            elevation=keys_elevation,  # after RBAC and the account's read (#2304 slice 3b)
        )
    )
    # #906 D1a (E28-T02): the profile store, the order path's effective-profile cache over it and
    # the facade over both, with the T01 counters (real backend only). The lifespan disposes of it.
    # D3a: the facade announces each committed write on the process's bus (24 Sec.9.2).
    profiles = wire_profiles(resolved, metrics_facade, ctx.bus.bus)
    app.state.profiles = profiles
    # D3e: each committed write tells its account's sockets (`profiles.changed`, 23 Sec.15.9),
    # through the hub's `broadcast_system`; the lifespan starts it and stops it before the bus
    # drains. None where no store publishes (the fake backend).
    app.state.profile_notices = (
        None
        if profiles is None
        else ProfileNotices(ctx.bus.bus, resolved.environment.value, ws_hub, metrics_facade)
    )
    # #906 D1c: `listAccountProfiles` and `getAccountProfile`, inside the caller's grants: the
    # session resolver loads them (a test may inject its own), and each read resolves its account
    # first through the M13 store built above for `ctx.accounts`' row gauges (real backend only).
    profiles_resolver: SnapshotResolver | None = principal_resolver
    if profiles_resolver is None and identity is not None:
        profiles_resolver = SessionSnapshotResolver(
            lambda: ctx.auth.sessions, identity, grants=True
        )
    app.include_router(
        make_profiles_router(
            None if profiles is None else profiles.repository,
            None if accounts_counts is None else AccountsRepository(accounts_counts),
            _LazyAuditEmitter(ctx.audit),
            profiles_resolver,
            auth=ctx.auth,  # a refusal names the caller's session (#4174)
        )
    )
    # E27-T04 (#837): per-account health and the wallet cache, on both backends; the lifespan starts
    # and stops it, and `ctx.accounts.account_health` is its `feed`, the private-WS consumer's. It
    # serves the `wallet` topic built above, and its key standing reads the self-check's results
    # (none on the fake backend).
    account_health = wire_account_health(
        resolved, metrics_facade, topic=ws_wallet, selfcheck=selfcheck
    )
    app.state.account_health = account_health
    ctx.accounts.attach_account_health(account_health.feed)
    # #906 D2: the profile writes and the default binding's move, Owner only and path-gated with
    # `risk_caps` (SR-E28-02), each audited ahead of its commit; a relaxing one notifies the Owner
    # in its transaction (SR-E28-01), and the second pass reads this environment's catalogue
    # (C-2.11). After the account health wiring: the save's sizing warnings read its wallet cache.
    warnings = SaveTimeFigures(
        account_health.wallets, lambda: ctx.ingestion.instruments, lambda: ctx.ingestion.tickers
    )
    app.include_router(
        make_profile_writes_router(
            profile_writes(profiles, ctx, warnings=warnings),
            _LazyAuditEmitter(ctx.audit),
            profiles_resolver,
            auth=ctx.auth,  # a refusal names the caller's session (#4174)
            measures=SaveMeasures.bound(metrics_facade),  # each save counted and timed (D3b)
        )
    )
    # #895 (E27-S01): `listExchangeAccounts` and `createExchangeAccount` over the M13 store built
    # above (real backend only), in the caller's grants (the profiles' resolver), each account with
    # the monitor's and the wallet cache's status.
    app.include_router(
        make_exchange_accounts_router(
            None if accounts_counts is None else AccountsRepository(accounts_counts),
            _LazyAuditEmitter(ctx.audit),
            profiles_resolver,
            environment=resolved.environment.value,
            statuses=AccountStatusReader(account_health, account_health.wallets),
            auth=ctx.auth,  # a refusal names the caller's session (#4174)
        )
    )
    # #837 W3: the one order-entry gate every submit path consults, the maintenance check first and
    # then the account check (key standing and health; the wallet only feeds its sizing flag),
    # synchronous and never flag-gated (C-2.21, C-4.14). The flag runtime holds no gate until this
    # composes it, so no holder ever takes one without the account check; the runtime and
    # `app.state` serve this one.
    app.state.order_entry_gate = feature_flags.compose_order_entry_gate(
        account_health.order_entry_check
    )
    # #913 slice 3E (20 Sec.6.2): the OMS runtime over that gate, the shared profile cache above
    # and the persistence bundle's sink when there is one; the lifespan starts it after the
    # account health runtime and stops it right after the gateway. None on the fake backend.
    app.state.oms_runtime = build_oms_runtime(
        ctx,
        resolved,
        metrics=metrics_facade,
        audit=_LazyAuditEmitter(ctx.audit),
        gate=app.state.order_entry_gate,
        standings=account_health.standings,
        oms_enabled=feature_flags.oms_enabled,
        live_enabled=feature_flags.live_enabled,
        profiles=None if profiles is None else profiles.effective,
        persistence=persistence,
        feed=machine_feed,
    )
    # #913 slice 3F (24 Sec.8.4): `placeOrder` over that runtime, mounted whatever
    # `trading.oms_enabled` says (it gates admission). The principal is the session's with its
    # trade grants; a test-injected `principal_resolver` wins. The fake backend composes neither
    # an identity nor a runtime, so it answers 501.
    order_principals: OrderPrincipals | None = principal_resolver
    if order_principals is None and identity is not None:
        trade_grants = SqlAlchemyScopeSource(
            SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "order-principal")
        )
        order_principals = SessionTradingPrincipalResolver(
            lambda: ctx.auth.sessions, identity, trade_grants
        )
    order_records = OmsAudit(_LazyAuditEmitter(ctx.audit), environment=resolved.environment.value)
    app.include_router(
        make_orders_router(
            order_principals,
            lambda: app.state.oms_runtime,
            audit=_LazyAuditEmitter(ctx.audit),
            records=order_records,
            oms_enabled=feature_flags.oms_enabled,
            metrics=metrics_facade,
            auth=ctx.auth,
        )
    )
    # #913 slice 4 S4-E (24 Sec.8.4, the exit routes): `cancelAllOrders`' own router over the same
    # runtime, principals and records, included ahead of the exit routes' router (the 19:43Z
    # ruling; pinned with the exit routes' below). `trading.oms_enabled` never gates it: a cancel is
    # a risk-reducing exit (C-2.6).
    app.include_router(
        make_cancel_all_router(
            order_principals,
            lambda: app.state.oms_runtime,
            audit=_LazyAuditEmitter(ctx.audit),
            records=order_records,
            metrics=metrics_facade,
            auth=ctx.auth,
            protective=protective_writes,
        )
    )
    # #913 slice 4 (S4-D1; 24 Sec.8.4 "The exit routes"): `DELETE /orders/{orderId}` over the same
    # principal source and runtime. The order routers mount in this order (the orchestrator's ruling
    # of 2026-10-24 19:43Z): placeOrder's above, then cancel-all's own router (S4-E's
    # `api/order_cancel_all.py`, included between the two), then this one; pinned by
    # `test_order_exits_route.py::test_the_order_routers_mount_in_their_ruled_order`. It serves
    # `PATCH /orders/{orderId}` too, `amendOrder` (S4-D2b), on the same steps.
    app.include_router(
        make_order_exits_router(
            order_principals,
            lambda: app.state.oms_runtime,
            audit=_LazyAuditEmitter(ctx.audit),
            metrics=metrics_facade,
            auth=ctx.auth,
        )
    )
    # #2111: the start-up and nightly audit chain verify job (lifespan-started). #2966: the real
    # backend runs it with the real runner (an injected one, a test's, wins); the fake backend has
    # none: no job, and the lifespan logs `audit.verify_job_not_wired`.
    if audit_verify_runner is None and resolved.storage_backend == "real":
        audit_verify_runner = ChainVerifyRunner(ctx.audit, chain_break_events)
    app.state.audit_verify_job = build_audit_verify_job(
        ctx.audit, resolved, metrics_facade, audit_verify_runner
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
    # E42-T01: admin overview + capacity read models behind the audited admin-area dependency.
    admin_settings = build_system_settings(resolved)
    admin_overview, admin_capacity = build_admin_read_models(
        resolved, system_settings=admin_settings, disk_budget=app.state.disk_budget
    )
    app.include_router(
        make_admin_overview_router(
            admin_overview,
            admin_capacity,
            resolver=audit_resolver,
            audit=_LazyAuditEmitter(ctx.audit),
        )
    )
    app.include_router(
        make_admin_capacity_router(
            admin_capacity,
            admin_settings,
            resolver=audit_resolver,
            audit=_LazyAuditEmitter(ctx.audit),
        )
    )
    # E42-T07: the statechart inspector read API behind the same audited admin-area guard.
    inspector = build_statechart_inspector(
        store=None if persistence is None else persistence.snapshots,
        keys=None if persistence is None else hmac_keys,
    )
    app.include_router(
        make_statechart_router(
            inspector, resolver=audit_resolver, audit=_LazyAuditEmitter(ctx.audit)
        )
    )
    # E42-T05: the health report over the E04 registry's snapshot and the incident list, behind the
    # same guard. The list reads `incidents`, filled as each error or critical event is written.
    admin_health = AdminHealthService(
        health_registry,
        version=resolved.version,
        git_sha=resolved.git_sha,
        environment=resolved.environment.value,
    )
    admin_incidents = build_admin_incidents(resolved, system_settings=admin_settings)
    app.include_router(
        make_admin_ops_router(
            admin_health,
            admin_incidents,
            resolver=audit_resolver,
            audit=_LazyAuditEmitter(ctx.audit),
        )
    )
    app.include_router(
        make_admin_incident_ack_router(
            admin_incidents, resolver=audit_resolver, audit=_LazyAuditEmitter(ctx.audit)
        )
    )
    app.state.admin_overview_metrics = export_overview_metrics(
        ctx.metrics, env=resolved.environment.value
    )
    # E42-T05 (#966 BK-15): `cv_incidents_open`, the count the overview shows, refreshed by the
    # lifespan and served with no sample while the incidents cannot be read.
    app.state.incidents_open_gauge = build_open_incidents_gauge(
        resolved, system_settings=admin_settings
    )
    app.state.incidents_open_metrics = export_incident_metrics(
        ctx.metrics, env=resolved.environment.value, gauge=app.state.incidents_open_gauge
    )
    # E42-T03: list and set the feature flags, on the audited admin router.
    for flags_router in make_feature_flags_routers(
        feature_flags, resolver=audit_resolver, audit=_LazyAuditEmitter(ctx.audit)
    ):
        app.include_router(flags_router)
    # E16-T05: weekly cold-tier compaction on demand (async job, polled via /admin/jobs).
    _cold_registry = DatasetRegistry(resolved.parquet_root)

    async def _compact(
        symbols: list[str] | None, older_than_days: int | None, progress: Callable[[float], None]
    ) -> dict[str, object]:
        summary = await compact_all(
            _cold_registry,
            build_compactor(resolved, _kb_pg, _cold_registry),  # G7: behind the replay guard
            symbols=symbols,
            older_than_days=older_than_days,
            on_progress=progress,
        )
        return summary.as_result()

    app.include_router(
        make_recorder_admin_router(
            admin_jobs,
            _compact,
            _LazyAuditEmitter(ctx.audit),
            audit_resolver,
            # E16-T10: archive import (503 unless the real backend, coverage and the running disk
            # budget are composed; the import honours the budget's ladder and cap).
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
                budget=app.state.disk_budget,
            ),
        )
    )
    # E42-T05 (#966 Q15): every job's poll, on the audited admin router (AD-F22).
    app.include_router(
        make_admin_jobs_router(
            admin_jobs, resolver=audit_resolver, audit=_LazyAuditEmitter(ctx.audit)
        )
    )
    # E42-T05 (#966 Q10): the jobs a restart loses, saved at a clean stop, counted at the next boot.
    app.state.admin_jobs_lost = LostJobsCount(
        resolved.data_dir,
        admin_jobs,
        metrics_facade.get("cv_admin_jobs_lost_on_restart_total").child(),
    )
    # E42-T05 (#966 BK-4): the backup catalogue reads, `backups:read` on the audited admin router;
    # `501 not_implemented` until a backup engine records runs (`BACKUPS_CATALOGUED`).
    backups_catalogue = build_admin_backups(resolved, system_settings=admin_settings)
    app.include_router(
        make_admin_backups_router(
            backups_catalogue, resolver=audit_resolver, audit=_LazyAuditEmitter(ctx.audit)
        )
    )
    # BK-5: the backup series and the freshness the lifespan loads, also only once catalogued.
    app.state.backup_metrics = serve_backup_metrics(resolved, ctx.metrics)
    app.state.backup_freshness = build_backup_freshness(resolved, system_settings=admin_settings)
    # BK-8: a backup run (`backups:write`), `501` until a backup engine is wired, through the one
    # admission gate every backups service shares (BK-9, BK-10, BK-12 and BK-13 take this one); at
    # boot the lifespan ends the runs a restart lost (SR-BK7-05), counted with the jobs it lost.
    backups_gate = app.state.backups_gate = BackupJobGate()
    backup_runs, app.state.backup_lost_runs = build_backup_runs(
        resolved,
        admin_jobs,
        _LazyAuditEmitter(ctx.audit),
        gate=backups_gate,
        lost=metrics_facade.get("cv_admin_jobs_lost_on_restart_total").child(),
        system_settings=admin_settings,
        freshness=app.state.backup_freshness,  # BK-5's: a success moves the served gauge
    )
    app.include_router(
        make_admin_backup_runs_router(
            backup_runs, resolver=audit_resolver, audit=_LazyAuditEmitter(ctx.audit)
        )
    )
    # BK-10: a single-use download link (`backups:write`, one fresh `backups` step-up each), `501`
    # until the catalogue and an artefact store are wired, on the one gate above.
    backup_downloads = build_backup_downloads(
        resolved, backups_catalogue, gate=backups_gate, audit=_LazyAuditEmitter(ctx.audit)
    )
    app.include_router(
        make_admin_backup_links_router(
            backups_catalogue,
            backup_downloads,
            auth=ctx.auth,
            resolver=audit_resolver,
            audit=_LazyAuditEmitter(ctx.audit),
        )
    )
    # BK-12: delete a backup's artefact and keep its row (`backups:write`, one fresh `backups`
    # step-up each), `501` until an artefact remover is wired, on the one gate above.
    app.include_router(
        make_admin_backup_delete_router(
            backups_catalogue,
            build_backup_deletion(
                resolved,
                gate=backups_gate,
                audit=_LazyAuditEmitter(ctx.audit),
                system_settings=admin_settings,
                freshness=app.state.backup_freshness,
            ),
            auth=ctx.auth,
            resolver=audit_resolver,
            audit=_LazyAuditEmitter(ctx.audit),
        )
    )
    # BK-11: the token-addressed fetch of a link (no bearer needed; a sent one must resolve), over
    # the issue's links; `501` until the issue is wired on the real backend with an identity.
    backup_fetch = build_backup_fetch(
        resolved, backup_downloads, identity=identity, system_settings=admin_settings
    )
    app.include_router(make_admin_backup_download_router(backup_fetch, resolver=audit_resolver))
    # BK-9: verifying a backup (`backups:write`), `501` until a backup engine wires its verifier
    # (#3319), through the same one admission gate.
    app.include_router(
        make_admin_backup_verify_router(
            build_backup_verifications(
                resolved, admin_jobs, _LazyAuditEmitter(ctx.audit), gate=backups_gate,
                system_settings=admin_settings, trail=_LazyAuditQuery(ctx.audit),
                freshness=app.state.backup_freshness,  # BK-12's `recompute` reloads a kind
            ),
            resolver=audit_resolver,
            audit=_LazyAuditEmitter(ctx.audit),
        )
    )  # fmt: skip
    # E16-T06: retention manager (real backend only) + the owner purge (one fresh no-grace
    # `recorder_purge` code per purge, bound to the request; its key anchored durably).
    retention_manager = build_retention_manager(resolved, _LazyAuditEmitter(ctx.audit), _kb_pg)
    app.state.retention_manager = retention_manager

    async def _purge_elevation(
        request: Request, action_class: str, fingerprint: str
    ) -> JSONResponse | SpentGrant:
        principal = await audit_resolver.resolve(request) if audit_resolver else None
        session_id = None if principal is None else principal.session_id
        return await require_bound_elevation(
            ctx.auth,
            session_id,
            action_class,
            fingerprint=fingerprint,
            emitter=_LazyAuditEmitter(ctx.audit),
        )

    app.include_router(
        make_recorder_purge_router(
            admin_jobs,
            retention_manager,
            _LazyAuditEmitter(ctx.audit),
            audit_resolver,
            _purge_elevation,
            anchors=build_purge_anchors(resolved, _kb_pg),
        )
    )
    # E16-T08 (#492): the recorded-set reads, over the stored rows of the settings' env (C-2.11)
    # until the recorder runtime is bound; `503` without the real backend.
    app.state.recording_control = (
        StoredRecordingControl(SqlAlchemyRecordingReads(_kb_pg), resolved.environment.value)
        if _kb_pg is not None
        else None
    )
    app.include_router(
        make_recording_symbols_router(
            lambda: app.state.recording_control, audit_resolver, _LazyAuditEmitter(ctx.audit)
        )
    )
    # The sessions page (same env) and the disk budget's last report; `503` without them.
    app.state.recording_sessions = SqlAlchemyRecordingReads(_kb_pg) if _kb_pg is not None else None
    app.include_router(
        make_recording_reports_router(
            lambda: app.state.recording_control,
            lambda: app.state.recording_sessions,
            lambda: app.state.disk_budget,
            resolved.environment.value,
            audit_resolver,
            _LazyAuditEmitter(ctx.audit),
        )
    )
    # The retention policy set, replaced whole behind the `recorder` step-up; `apply_now` runs
    # one sweep through the admin jobs (409 while `retention_enabled` is off).
    app.state.retention_policies = (
        SqlAlchemyRetentionPolicies(_kb_pg) if _kb_pg is not None else None
    )
    app.include_router(
        make_recording_retention_router(
            lambda: app.state.retention_policies,
            admin_jobs,
            lambda: app.state.retention_manager,
            resolved.retention_enabled,
            audit_resolver,
            _LazyAuditEmitter(ctx.audit),
        )
    )
    # The recording status, computed once a second (the WS runtime starts and stops it):
    # `not_deployed` until the recorder runtime binds `app.state.recording_runtime` (#2188).
    app.state.recording_runtime = None
    recording_status = RecordingStatusCache(
        lambda: app.state.recording_runtime, app.state.disk_budget
    )
    app.state.ws_runtime.recorder_status = recording_status
    ws_recorder.attach(recording_status)  # its frames go out on each computation
    app.include_router(
        make_recording_status_router(recording_status, audit_resolver, _LazyAuditEmitter(ctx.audit))
    )
    # The recorded-set writes: no control has them until the recorder runtime is bound (#2188),
    # so `recording_writer` stays `None` and every write answers `503` until then, and after it
    # until the recorder's startup has completed (`recording_ready`, read per request: SEC-4).
    app.state.recording_writer = None
    app.state.recording_ready = lambda: False
    # #2188 S4b: the recorder on the real backend: the policy, the sessions and the writer under
    # one runtime that the supervisor starts (a request never does), and #492's control over it.
    # One `PolicyConfig` serves both, so the control's default retention cannot drift from the
    # policy's.
    recorder_config = policy_config(resolved)
    recorder: ComposedRecorder | None = None
    if _kb_pg is not None and coverage_service is not None and health_pg is not None:
        repo = SqlAlchemyRecorderRepository(_kb_pg)
        recorder = build_recorder(
            resolved, recorder_config, recorded=repo, sessions=repo, counters=repo,
            rows=SqlAlchemyRecordingReads(_kb_pg), audit=_LazyAuditEmitter(ctx.audit),
            bus=ctx.bus.bus, budget=app.state.disk_budget, invalidate=coverage_service.invalidate,
            topics=ctx.exchange_bybit.stream_for_topic, sinks=questdb_sinks(resolved),
            events=PgSystemEventWriter(health_pg, redact_details=system_event_redactor()),
        )  # fmt: skip
        runtime = recorder.runtime
        ctx.recorder.attach_runtime(runtime)
        app.state.recording_ready = lambda: runtime.startup_complete
        register_recorder_probe(health_registry, ctx.recorder.health)
    app.state.recorder = recorder
    bind_recording_runtime(app.state, recorder, recorder_config)

    async def _recording_elevation(session_id: uuid.UUID | None) -> JSONResponse | None:
        return await require_session_elevation(ctx.auth, session_id, "recorder")

    app.include_router(
        make_recording_writes_router(
            lambda: recording_writer(app.state), audit_resolver, _LazyAuditEmitter(ctx.audit),
            _recording_elevation, lambda symbol: _catalogue_listed(ctx, symbol),
        )
    )  # fmt: skip
    # E16-T05: nightly roll-off composition (constructed only; scheduling is flag-gated).
    app.state.rolloff_job = build_rolloff_job(
        resolved,
        _LazyAuditEmitter(ctx.audit),
        _kb_pg,
    )
    # QA defect #1622 blocker: `/market/klines` (E08-S06 core deliverable)
    # was missing entirely — cache-only reads today (`ctx.storage.
    # market_data`); backfilling from the exchange itself is wired once
    # E08-T02 lands a real exchange adapter (see `api/market.py`
    # module docstring). #2092: authorised through the session-backed `audit_resolver`
    # (`marketdata:read`, as `/market/bars` below), so only a verified session with the
    # permission is served (401 / 403 otherwise). Without an identity provider (fake
    # backend) the resolver is `None` and every request fails closed with `501`, not with a
    # silent unauthenticated read (C-12.4, PR #1626 review finding: this route was
    # previously reachable by any mesh caller with no RBAC check at all).
    app.include_router(
        make_market_router(
            lambda: ctx.storage.market_data,
            principal_resolver=audit_resolver,
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
            trade_totals=trade_totals_source(ctx),
            principal_resolver=audit_resolver,
            symbol_listed=lambda sym: _catalogue_listed(ctx, sym),
            qty_step=lambda sym: _catalogue_qty_step(ctx, sym),  # SR-E12-03 volume/delta floor
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
    # `wire_instrument_catalogue()` attaches one (`_compose_instrument_catalogue`).
    # #2561: the same session-backed resolver as the routes above (501 only without identity).
    app.include_router(
        make_instruments_router(
            lambda: ctx.ingestion.instruments, principal_resolver=audit_resolver
        )
    )
    _compose_instrument_catalogue(ctx, resolved, public_rest)
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
    # E13-T02: the indicator catalogue (static, code-defined); same resolver/fail-closed rules.
    # E13-T03: the same catalogue validates `/indicator-presets` writes (mounted below).
    indicator_catalogue = default_catalogue()
    app.include_router(
        make_indicators_router(indicator_catalogue, principal_resolver=audit_resolver)
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
            audit_writer_sink(_LazyAuditEmitter(ctx.audit), acting=acting_user),
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
        store=rule_store,
        audit=_rules_audit,
        broadcast=_rules_broadcast,
    )
    rules_actor = (
        SessionRulesActorResolver(
            lambda: ctx.auth.sessions,
            lambda: ctx.auth.step_up,
            identity,
            _LazyAuditEmitter(ctx.audit),
        )
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

    # E40-T04: the delivery inbox, mounted before the CRUD router (whose `/alerts/{alertId}`
    # would take `GET /alerts/deliveries`), and the unified notification history.
    app.include_router(
        make_alert_deliveries_router(
            lambda: SqlAlchemyAlertDeliveryRepository(_alert_pg),
            rules_actor.resolve if rules_actor else None,
            _LazyAuditEmitter(ctx.audit),
            metric=_alert_delivery_sink(metrics_facade),
            on_change=ws_alerts.deliveries_changed,
        )
    )
    # E40-T04: the `alerts` topic reads the deliveries on the real backend; on the fake one it
    # stays unattached and its subscriptions stay `snapshot_pending` (no I/O).
    if resolved.storage_backend == "real":
        ws_alerts.attach(SqlAlchemyAlertDeliveryRepository(_alert_pg))
    ctx.alerts.bind_topic(ws_alerts)

    async def _visible_rules(actor: Actor) -> frozenset[str]:
        mgr = ctx.rules.manager()  # the rules module stopped: no rule rows, never every rule
        return frozenset() if mgr is None else await mgr.visible_rule_ids(actor)

    # C-2.11: account-bound rows are this process's exchange environment only. Built once, so an
    # environment the read model does not know fails the boot, not the first request.
    _notifications = SqlAlchemyNotificationRepository(_alert_pg, env=resolved.environment.value)
    app.include_router(
        make_notifications_router(
            lambda: _notifications,
            rules_actor.resolve if rules_actor else None,
            _visible_rules,
        )
    )
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
        dispatcher = _alert_dispatcher(
            _alert_pg, metrics_facade, resolved.alerts_webhook_enabled,
            on_change=ws_alerts.deliveries_changed,
        )  # fmt: skip
        ctx.alerts.bind(
            _alert_evaluator_factory(
                ctx, _alert_pg, metrics_facade, wake=dispatcher.notify, feed=machine_feed
            ),
            dispatcher,
        )
    # E14-T01: owner-scoped /drawings; callers from the session (`audit_resolver`, as for
    # /admin/audit; None without an identity store -> 401), RBAC via `auth.scopes.enforce`.
    # Postgres on the real backend only: the fake backend answers 503 without any I/O.
    app.state.drawings_repository = (
        SqlAlchemyDrawingRepository(
            SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "drawings")
        )
        if resolved.storage_backend == "real"
        else None
    )
    app.include_router(
        make_drawings_router(
            lambda: app.state.drawings_repository,
            audit_resolver,
            _LazyAuditEmitter(ctx.audit),
            metrics=app.state.drawings_metrics,
            layouts=lambda: app.state.workspaces_repository,  # E15-T01: GET ?layout_id
        )
    )
    # E15-T01: workspaces metrics (conflicts/panes/duration recorded by the router) + 90-day
    # soft-delete purge and the users-per-bucket gauge. `workspaces` has no forbid-delete trigger.
    app.state.workspaces_metrics = WorkspacesMetrics(
        conflicts=metrics_facade.counter(
            "cv_workspace_conflicts_total", "Stale If-Match 412s.", ("resource",), max_series=2
        ),
        layout_panes=metrics_facade.histogram(
            "cv_layout_panes", "Panes per changed layout write.", buckets=(0, 1, 2, 4, 8, 12, 16)
        ),
        users=metrics_facade.gauge(
            "cv_workspace_users", "Users by live-workspace bucket.", ("bucket",),
            max_series=len(USER_BUCKETS),
        ),
        purged=metrics_facade.counter(
            "cv_workspaces_purged_total", "Workspaces/layouts hard-purged.", ("kind",),
            max_series=2,
        ),
        request_seconds=metrics_facade.histogram(
            "cv_workspace_request_seconds", "Duration per /workspaces operation.",
            ("operation",), buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
            max_series=len(OPERATIONS),
        ),
    )  # fmt: skip
    # E15-T01: owner-scoped /workspaces; callers from the session (`audit_resolver`, as for
    # /admin/audit; None without an identity store -> 401), RBAC via `auth.scopes.enforce`.
    # Postgres on the real backend only: the fake backend answers 503 without any I/O.
    app.state.workspaces_repository = (
        SqlAlchemyWorkspaceRepository(
            SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "workspaces")
        )
        if resolved.storage_backend == "real"
        else None
    )
    app.state.workspaces_purge_task = (
        WorkspacesPurgeTask(
            app.state.workspaces_repository,
            _retention,
            app.state.workspaces_metrics.purged,
            app.state.workspaces_metrics.users,
        )
        if app.state.workspaces_repository is not None
        else None
    )
    app.include_router(
        make_workspaces_router(
            lambda: app.state.workspaces_repository,
            audit_resolver,
            _LazyAuditEmitter(ctx.audit),
            metrics=app.state.workspaces_metrics,
        )
    )
    # E13-T03: owner-scoped /indicator-presets with the built-ins (`scope: self`, as /drawings),
    # every write checked against the catalogue `/indicators` serves. Postgres on the real backend
    # only: the fake backend answers 503 without any I/O.
    app.state.indicator_presets_repository = (
        SqlAlchemyIndicatorPresetRepository(
            SqlAlchemyRelationalRepository(resolved.pg_dsn.get_secret_value(), "indicator-presets")
        )
        if resolved.storage_backend == "real"
        else None
    )
    app.state.indicator_presets_metrics = IndicatorPresetMetrics(
        presets=metrics_facade.gauge(
            "indicator_presets_total", "Live indicator presets of all owners by builtin.",
            ("builtin",), max_series=2,
        ),
        denied=metrics_facade.counter(
            "indicator_preset_denied_total", "Indicator-preset writes refused for their target.",
            ("reason",), max_series=2,
        ),
    )  # fmt: skip
    # The gauge's first read, at startup (lifespan-started), so its series precede any write.
    app.state.indicator_presets_gauge = IndicatorPresetsGaugePrimer(
        lambda: app.state.indicator_presets_repository, app.state.indicator_presets_metrics
    )
    app.include_router(
        make_indicator_presets_router(
            lambda: app.state.indicator_presets_repository,
            audit_resolver,
            _LazyAuditEmitter(ctx.audit),
            indicator_catalogue,
            metrics=app.state.indicator_presets_metrics,
        )
    )
    # E08-S05: maintained L2 book snapshot (503 while resyncing, never a patched book).
    app.include_router(
        make_orderbook_router(lambda: ctx.ingestion.books, principal_resolver=audit_resolver)
    )
    # Middleware order, outermost first (Starlette: last added = outermost):
    #   HttpDuration -> Correlation -> MeshOnly -> Csrf -> Cors (ADR-0038) -> IdleLock (#2300)
    #   -> enrolment-only guard (#2295) -> view-as guard (#3085) -> read-only/step-up guard
    #   -> routes.
    # Outside all of it, Starlette's error middleware included, `_StampedApp` wraps the stack in
    # BK-11's `NoStoreNoReferrer` (the backup fetch's path) and, outermost, #3990's `NoSniff`.
    # ADR-0038 2c (#3519): the CORS layer sits inside MeshOnly (an off-mesh peer gets no CORS
    # answer) and the CSRF guard, outside idle-lock. It and the guard's token refusals take this one
    # policy and one flag reader; an empty allow-list (the default) or the flag off changes nothing.
    cors = CorsPolicy(resolved.allowed_origin_set)
    app.add_middleware(CorsGateMiddleware, policy=cors, enabled=feature_flags.backend_connection)
    # #2090 (SR-041/SR-042): CSRF runs inside MeshOnly, so off-mesh traffic never
    # reaches a session lookup or an audit write, and outside every route-level
    # guard (read-only/step-up, RBAC): no write reaches them without a valid token.
    app.add_middleware(
        CsrfMiddleware,
        codec=csrf_codec,
        sessions=lambda: ctx.auth.sessions if ctx.auth.sessions_is_active else None,
        audit=_LazyAuditEmitter(ctx.audit),
        allowed_origins=cors.origins,
        operations=frozenset(declared_operations(spec)),
        clock=auth_clock or (lambda: datetime.now(UTC)),
        tracker=csrf_audits,
        cors=cors,
        cors_enabled=feature_flags.backend_connection,
    )
    # E09-T04: rejects off-mesh requests before any credential is evaluated.
    app.add_middleware(
        MeshOnlyMiddleware,
        allow_list=CidrAllowList(list(resolved.mesh_cidrs)),
        trusted_proxy_header=resolved.mesh_trusted_proxy_header,
        trusted_proxy_address=resolved.mesh_trusted_proxy_address,
    )
    # E04-T02: outermost of the guards (added last of the trio) so every request - even a mesh
    # rejection - gets a correlation id and the X-Correlation-Id response header.
    app.add_middleware(CorrelationMiddleware)
    # #902: counts each denied request by route and role; inside HttpDuration, outside the trio.
    app.add_middleware(AuthzDenialMiddleware, counter=metrics_facade.get(AUTHZ_DENIALS_METRIC))
    # #2421: outermost (added last), outside the Correlation -> MeshOnly -> Csrf guard trio, which
    # must stay adjacent and in that order. Times every request, mesh/CSRF refusals included; it
    # neither reads nor needs the correlation id.
    app.add_middleware(HttpDurationMiddleware, histogram=metrics_facade.get(HTTP_DURATION_METRIC))
    # E09-T03 / #1648: a served route without an RBAC declaration fails the build.
    assert_app_routes_declared(app, spec)
    # #2551: /openapi.json publishes the contract's operations for the raw-body routers.
    install_contract_openapi(app, spec)
    return app


def _alert_dispatcher(
    pg: SqlAlchemyRelationalRepository,
    facade: Metrics,
    webhook_enabled: bool,
    *,
    on_change: Callable[[Sequence[int]], Awaitable[None]] | None = None,
) -> AlertDispatcher:
    """E40-T04: `alert.deliver` outbox poller. Email stays disabled (suppressed) until the
    E04 relay transport is provisioned; no network transport is constructed here. *on_change*
    (the `alerts` topic) is told of each settled batch."""
    adapters = default_adapters(None, webhook_enabled=webhook_enabled)  # refuses webhook=on
    sink = _alert_delivery_sink(facade)
    # The series the two alert.deliver outbox tickets read, bound at start: a series created by
    # its first dead row gives `increase()` nothing to subtract (AlertOutboxDeadLettered), and
    # the gauge reads 0 until the first sample (AlertOutboxBacklog).
    for name in ("cv_outbox_dead_total", "cv_outbox_depth"):
        sink(name, (TOPIC_ALERT_DELIVER,))
    for stage in ("evaluate", "dispatch"):  # #3349: the four owner-skip series, at 0 until a skip
        for reason in ("inactive", "unreadable"):
            sink("cv_alert_owner_skipped_total", (stage, reason))
    return AlertDispatcher(
        SqlAlchemyAlertDispatchStore(pg),
        adapters,
        worker=f"api-{os.getpid()}-{uuid.uuid4().hex[:8]}",
        now=lambda: datetime.now(UTC),
        owners=OwnerGate(SqlAlchemyIdentityProvider(pg)),
        metric=sink,
        on_change=on_change,
    )


def _alert_owner_skipped(facade: Metrics) -> Any:
    """`cv_alert_owner_skipped_total` (#3349): the evaluator and the dispatcher each count their own
    `stage`; identical re-registration returns the one metric."""
    return facade.counter(
        "cv_alert_owner_skipped_total",
        "Alert firings, disarms and deliveries skipped: the owner is not active or unreadable.",
        ("stage", "reason"),
        max_series=4,
    )


def _alert_delivery_sink(facade: Metrics) -> Callable[[str, tuple[str, ...]], Any]:
    """The `cv_alert_delivery_*` and `cv_outbox_*` sink shared by the dispatcher and the desktop
    report-back route (E40-T04): identical re-registration returns the same series."""
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
        "cv_outbox_depth": facade.gauge(
            "cv_outbox_depth", "Unprocessed, not-dead outbox rows by topic.", ("topic",),
            max_series=8),
        "cv_alert_owner_skipped_total": _alert_owner_skipped(facade),
    }  # fmt: skip

    def _sink(name: str, labels: tuple[str, ...]) -> Any:
        b = m[name]
        return b.labels(*labels) if labels else b.child()

    return _sink


def _alert_evaluator_factory(
    ctx: AppContext,
    pg: SqlAlchemyRelationalRepository,
    facade: Metrics,
    *,
    wake: Callable[[], None] | None = None,
    feed: MachineStatePort | None = None,
) -> Callable[[], Awaitable[AlertEvaluator | None]]:
    """E40-T03: evaluator over the rules module's pushed metric source (shared E35 bus). With
    *wake* (E40-T04, the dispatcher's `notify`), a committed firing is delivered at once."""
    metric = _alert_metric_sink(facade)

    async def _make() -> AlertEvaluator | None:
        source = ctx.rules.metric_source
        if source is None:  # E35 evaluator off: no metric bus to subscribe to
            return None
        audit = _LazyAuditEmitter(ctx.audit)
        firing: FiringStore = SqlAlchemyAlertFiringStore(
            pg, topic=TOPIC_ALERT_DELIVER, dedup_key=alert_deliver_dedup_key
        )
        store = firing if wake is None else WakingFiringStore(firing, wake)
        return AlertEvaluator(
            store, source, owners=OwnerGate(SqlAlchemyIdentityProvider(pg)),
            charts=AlertCharts(feed=feed), audit=audit, metrics=AlertMetrics(metric),
        )  # fmt: skip

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
        "cv_alert_owner_skipped_total": _alert_owner_skipped(facade),
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


def _catalogue_qty_step(ctx: AppContext, symbol: str) -> Decimal | None:
    """`symbol`'s lot step for SR-E12-03's `volume`/`delta` floor, read per call (a catalogue may
    attach after boot). `None` (no catalogue or snapshot yet, or not listed): refused, not 1."""
    scheduler = ctx.ingestion.instruments
    snap = scheduler.snapshot() if scheduler is not None else None
    inst = snap.get(symbol) if snap is not None else None
    return None if inst is None else inst.qty_step


def _catalogue_scales(ctx: AppContext, symbol: str) -> tuple[int, int] | None:
    """The bars wire's floor scales (`23-ws-protocol.md` §3.4): the decimal places of the
    symbol's tick size and qty step; None while the catalogue does not list it."""
    scheduler = ctx.ingestion.instruments
    snap = scheduler.snapshot() if scheduler is not None else None
    inst = snap.get(symbol) if snap is not None else None
    return None if inst is None else (_places(inst.tick_size), _places(inst.qty_step))


def _places(step: Decimal) -> int:  # `0.10` -> 1, `0.001` -> 3, `5` -> 0
    exponent = step.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


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


def _compose_instrument_catalogue(
    ctx: AppContext, settings: Settings, public_rest: PublicRest | None = None
) -> None:
    """#2561: attach the E08-S01-2 catalogue on the real backend whenever the app talks to the
    exchange: `CV_FEED=live`, or the public WS behind `ingestion_ws_enabled`, which admits only
    catalogue symbols. The dev and CI defaults (synthetic feed, flag off) make no exchange call
    (C-13.5); `/instruments` answers 503 there, or 501 without an identity provider. #2599: the
    catalogue fetches through the public WS's REST client when there is one, so one governor
    (C-12.7). Ingestion stops the scheduler, then closes the client and the pool."""
    if settings.storage_backend != "real" or not (
        settings.feed is FeedMode.LIVE or settings.ingestion_ws_enabled
    ):
        return
    rest = (public_rest or PublicRest(ctx)).client
    relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "instruments")
    wire_instrument_catalogue(
        ctx,
        fetch_instruments=ctx.exchange_bybit.instruments_fetcher(rest),
        relational=relational,
        fetch_risk_limits=ctx.exchange_bybit.risk_limits_fetcher(rest),
    )
    ctx.ingestion.attach_closer(relational.dispose)


def wire_instrument_catalogue(
    ctx: AppContext,
    *,
    fetch_instruments: InstrumentsFetcher,
    relational: SqlAlchemyRelationalRepository,
    fetch_risk_limits: RiskLimitsFetcher | None = None,
) -> InstrumentsRefreshScheduler:
    """Compose the E08-S01-2 catalogue: the exchange adapter's neutral
    instruments fetcher (M4, built by the adapter and passed in as the
    neutral `InstrumentsFetcher` port) + Postgres repository (M10) + bus
    publisher (M5) -> ingestion (M6) scheduler. Only this composition root
    sees all four modules (C-3.1). S-RL (#913): the adapter's risk-limit fetcher (same client,
    same governor) feeds the tiers kept beside the catalogue. S4-S-c: on the real backend the
    order path's symbols, read over the catalogue's own pool (its loop), seed the tier refresh;
    elsewhere nothing seeds it."""
    bus = ctx.bus.bus
    env = ctx.settings.environment.value

    async def _publish(event: InstrumentUpdatedEvent) -> None:
        topic = Topic(env=env, domain="instruments", symbol=event.symbol, detail="updated")
        await bus.publish(topic, event)

    scheduler = InstrumentsRefreshScheduler(
        fetch_instruments_info=fetch_instruments,
        repository=SqlAlchemyInstrumentsRepository(relational),
        publish=_publish,
        fetch_risk_limits=fetch_risk_limits,
        order_path_symbols=(
            SqlAlchemyOrderPathSymbols(relational, statement_timeout_ms=1000)
            if ctx.settings.storage_backend == "real"
            else None
        ),
    )
    ctx.ingestion.attach_instruments(scheduler)
    return scheduler


def _repair_hooks(*hooks: RepairHook) -> RepairHook:
    """The series store's one repair hook (#2787 D2-H1): each of `hooks` in order, the bars
    publisher's `history_repair`, then the indicator engine's (E13-T02). A hook that raises does
    not stop the next; the first error is raised once all have run, and the store counts it."""

    def repair(symbol: str, spec: BarSpec, min_history: int) -> None:
        failure: Exception | None = None
        for hook in hooks:
            try:
                hook(symbol, spec, min_history)
            except Exception as exc:  # the next hook still runs; the first error is raised
                failure = failure or exc
        if failure is not None:
            raise failure

    return repair


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


class PublicRest:
    """#2599: a credential-less public REST client, and so one token-bucket governor (C-12.7),
    shared by every public consumer of one app (the public WS's clock probe, klines and recent
    trades, and the instrument catalogue). Ingestion closes it on stop, after the components
    that use it. A holder, so this composition root never names the adapter's client type."""

    def __init__(self, ctx: AppContext) -> None:
        self.client = ctx.exchange_bybit.public_rest_client(ctx.settings.environment.value)
        ctx.ingestion.attach_closer(self.client.aclose)


def wire_public_ws(
    ctx: AppContext,
    kline_boundary: KlineHotBoundary | None = None,
    public_rest: PublicRest | None = None,
    machine_feed: MachineStatePort | None = None,
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
        adapter.ws_connection_budget.lane("public"),  # one per-IP budget (24 §14.2 rule 13)
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
    rest = (public_rest or PublicRest(ctx)).client
    guard = wire_clock_offset(ctx, rest_client_fetcher(rest))

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
            supervisor=B14BookSupervisor(feed=machine_feed),
            tick_size=_tick_size,  # #3806: a tick-size change under a LIVE book resyncs it
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


def trade_totals_source(ctx: AppContext) -> TradeTotalsSource:
    """SR-E12-02 (#2093): the stored-print count behind `/market/bars`'s non-time estimate, read
    from `ctx.storage.market_data` on each call (storage starts after the routes are built)."""

    async def totals(symbol: str, rng: TimeRange) -> TradeTotals:
        return await ctx.storage.market_data.trade_totals(symbol, rng)

    return totals


def wire_clock_offset(ctx: AppContext, fetch_server_time: ServerTimeFetcher) -> ClockGuard:
    """E04-T06: compose ClockGuard over the adapter's REST server-time fetcher
    (`rest_client_fetcher`); its offset corrects the exchange latency stage.
    The guard's periodic task is started by whoever owns the REST client."""
    guard = ClockGuard(fetch_server_time)
    ctx.ingestion.attach_clock(guard)
    return guard
