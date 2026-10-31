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
from typing import Any, Final, Protocol

from candleviewer.admin.audited import audit_exempt, audited
from candleviewer.audit.actions import validate_action
from candleviewer.audit.break_halt import AuditBreakHalt, AuditBreakHaltService
from candleviewer.audit.export_signing import (
    ExportSigningFailed,
    Signer,
    SigningKey,
    SigningKeyDirectory,
)
from candleviewer.audit.lane_journal import key_id
from candleviewer.audit.machine_events import (
    MachineEventStore,
    MachineEventUnavailable,
    MachineEventWalSink,
    SinkMetrics,
    frames_left,
)
from candleviewer.audit.metrics import export_audit_lane_metrics
from candleviewer.audit.models import AuditEmission, AuditOutcome, ExchangeEnv, Severity
from candleviewer.audit.redact import redact
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.service import AuditService, LaneKeyLoader, LaneNotWired
from candleviewer.audit.verify_job import AuditVerifyJob
from candleviewer.audit.verify_runner import VerifyRunner
from candleviewer.audit.writer import (
    AuditWriter,
    keyed_record_id,  # the OMS's keyed audit ids (#913, C-3.3)
)
from candleviewer.observability.context import current_request_uuid
from candleviewer.observability.metrics import Metrics
from candleviewer.secrets import (
    AuthKeyStore,
    CandidateKeys,
    CredentialBorrower,
    CredentialStore,
    ExportKeyStore,
    ExportSigner,
    KcvStore,
    KeyDestroyer,
    LoopSigning,
    LoopStoreFactory,
    RotationRunning,
    SecretsError,
    SecretsLifecycle,
    SecretsLifecycleFacade,
    SecretsMetadata,
    SecretsMetadataFacade,
    SecretsService,
    SigningKeyRotator,
    SigningKeys,
    export_secrets_metrics,
    mint_borrower,
    mint_candidate_keys,
    mint_export_signer,
    mint_key_destroyer,
    mint_loop_signing,
    mint_rotation_running,
    mint_signing_key_rotator,
    mint_signing_keys,
)
from candleviewer.settings import Settings

#: What `AppContext.secrets` holds: lifecycle + health only (C-3.2). `admin` is injected
#: `SecretsMeta`; M4 is injected the one `CredentialBorrower` minted here. Key import (#836) gets
#: `SecretsBundle.candidate_keys`, minted here too, so it imports no M2 module.
SecretsHandle = SecretsLifecycle
SecretsMeta = SecretsMetadata
#: The order lane's loop signing (#913 L3b), so the lane's wiring names no `secrets` type.
LoopSigningHandle = LoopSigning
#: #913 L1d: the borrower a `LoopSigningHandle` signs with, as the adapter's `lane_trading_port`
#: takes it, so the lane's wiring names no `secrets` type either.
LoopSigningBorrower = CredentialBorrower


class LaneAuditWriter(Protocol):
    """`AuditWriter.emit`, the durable append M2 writes its records ahead through (C-2.9), as the
    order lane holds its own writer (#913 L1d): L2's lane writer (`build_lane_audit_writer`),
    never the serving loop's. Each parameter is the writer's, of its kind and with its default."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: str | uuid.UUID | None = None,
        actor_ip: str | None = None,
        session_id: str | uuid.UUID | None = None,
        object_kind: str | None = None,
        object_id: str | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: Severity = Severity.INFO,
        reason: str | None = None,
        after_state: dict[str, Any] | None = None,
        request_id: str | uuid.UUID | None = None,
        env: ExchangeEnv | None = None,
    ) -> None: ...


class LaneSigningBinder(Protocol):
    """`SecretsBundle.lane_signing` (#913 L1d): called on the order lane's loop with the lane's own
    audit writer, never the serving loop's, it binds signing there over a credential store M2
    builds on that loop and alone holds; `LoopSigning.aclose` closes it, then frees its pool."""

    def __call__(self, *, audit: LaneAuditWriter) -> LoopSigning: ...


@dataclass(frozen=True)
class SecretsBundle:
    """The narrow capabilities of one `SecretsService` (built once, in wiring); the export signer
    and its key directory are `audit`'s ports, for the export job (#889, ADR-0039), the directory
    also for `listAuditSigningKeys` and the export's own `503`, the rotator is `admin`'s, for
    `rotateAuditSigningKey`, and the running rotation the export route's, for its own `409`.
    `lane_signing(audit=)`, called on the order lane's loop with the lane's own audit writer, binds
    signing there (#913 L3b) over a credential store M2 builds on that loop (#913 L1d).
    `key_destroyer` destroys one stored key of one account (#898's delete and revoke)."""

    lifecycle: SecretsLifecycle
    metadata: SecretsMetadata
    exchange_borrower: CredentialBorrower
    candidate_keys: CandidateKeys
    export_signer: Signer
    signing_keys: SigningKeyDirectory
    signing_key_rotator: SigningKeyRotator
    rotation_running: RotationRunning
    lane_signing: LaneSigningBinder
    key_destroyer: KeyDestroyer


__all__ = [
    "AuditBreakHaltHandle",
    "AuditHandle",
    "AuditVerifyRunner",
    "LaneAuditWriter",
    "LaneNotWired",
    "LaneSigningBinder",
    "LoopSigningBorrower",
    "LoopSigningHandle",
    "MachineEventSinkHandle",
    "MachineEventSinkMetrics",
    "MachineEventSinkUnavailable",
    "SecretsBundle",
    "SecretsHandle",
    "SecretsMeta",
    "audit_lane_key_id",
    "audit_writer_sink",
    "build_audit_break_halt",
    "build_audit_service",
    "build_audit_verify_job",
    "build_lane_audit_writer",
    "build_machine_event_sink",
    "build_secrets_service",
    "export_audit_lane_metrics",
    "export_secrets_metrics",
    "keyed_record_id",
    "secrets_audit_row",
    "secrets_audit_sink",
    "secrets_bundle",
    "system_event_redactor",
    "unclaimed_machine_events",
]
AuditHandle = AuditService
AuditBreakHaltHandle = AuditBreakHaltService
#: The scheduled verify run's port (#2111), so `app` can type an injected runner.
AuditVerifyRunner = VerifyRunner
#: The `machine_events` sink (E50-T63), its metric handles and its fail-closed error, for the
#: statechart composition root, which may not import M19 (C-3.3).
MachineEventSinkHandle = MachineEventWalSink
MachineEventSinkMetrics = SinkMetrics
MachineEventSinkUnavailable = MachineEventUnavailable


#: The M2 records that page: a KEK that failed to load or re-wrap, and stranded rows (#2266);
#: a signing key that cannot be used, and a retired one that still held its seed (#889, ADR-0039
#: decision 2, Q3).
_SECRETS_ERRORS = frozenset(
    {
        "security.kek_load_failed",
        "security.kek_rotation_failed",
        "security.kek_rows_stranded",
        "security.audit_signing_key_unavailable",
        "security.audit_signing_key_material_destroyed",
        "security.audit_signing_key_rotation_failed",  # #889 S7: a rotation that did not commit
    }
)
#: M2 refusals (#2266; #889 S7's rotation): stored as denied, at warning, as the other refusals
#: are (C-12.8).
_SECRETS_REFUSED = frozenset(
    {"security.kek_rotation_refused", "security.audit_signing_key_rotation_refused"}
)
#: The audit export signing key's records (#889, ADR-0039 decision 7): `object_kind`
#: `audit_signing_key`, whose `key_id` is the export key's id, never an API key's.
_SIGNING_KEY_ACTIONS = ("security.audit_signing_key_", "security.audit_export_")
#: Members M2's `(action, fields)` port carries as `"true"`/`"false"`, stored as JSON booleans
#: (22 `rotateAuditSigningKey`: `retired_material_destroyed: true`); any other value raises
#: (`KeyError`) before the record is written or built, so a typo never records `false`.
_BOOLEANS = frozenset({"retired_material_destroyed"})
_BOOL = {"true": True, "false": False}


def _secrets_audit_columns(action: str, fields: dict[str, str]) -> dict[str, Any]:
    """The audit columns of one M2 record, for the WAL sink and the row builder alike. Fields
    are ids only; the actor comes from the wiring-bound caller identity, never the borrower."""
    signing_key = action.startswith(_SIGNING_KEY_ACTIONS)
    columns: dict[str, Any] = {
        "actor_label": f"{fields.get('actor_kind', 'system')}:{fields.get('actor_role', '')}",
        "actor_user_id": fields.get("actor_user_id"),
        "object_kind": (
            "audit_signing_key" if signing_key else "api_key" if "key_id" in fields else "kek"
        ),
        "object_id": fields.get("key_id", fields.get("active_key_id")),  # a rotation's new key
        "severity": Severity.ERROR if action in _SECRETS_ERRORS else Severity.INFO,
        "after_state": {k: _BOOL[v] if k in _BOOLEANS else v for k, v in fields.items()},
        "request_id": current_request_uuid(),  # the request the change is part of (#3990)
    }
    if action in _SECRETS_REFUSED:
        columns |= {"outcome": AuditOutcome.DENIED, "severity": Severity.WARNING}
    return columns


def secrets_audit_sink(audit: AuditService) -> Callable[[str, dict[str, str]], Awaitable[None]]:
    """M2 audit port -> durable `AuditWriter.emit` (write-ahead)."""

    async def sink(action: str, fields: dict[str, str]) -> None:
        await audit.writer.emit(action, **_secrets_audit_columns(action, fields))

    return sink


def _lane_audit_sink(writer: LaneAuditWriter) -> Callable[[str, dict[str, str]], Awaitable[None]]:
    """M2 audit port -> the order lane's own durable `emit` (write-ahead, C-2.9), the columns
    `secrets_audit_sink` writes through a service (#913 L1d)."""

    async def sink(action: str, fields: dict[str, str]) -> None:
        await writer.emit(action, **_secrets_audit_columns(action, fields))

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
    export_keys: ExportKeyStore | None = None,
    *,
    loop_store: LoopStoreFactory | None = None,
) -> SecretsBundle:
    """Construct M2 once and split it into narrow capabilities. No I/O; the KEK is loaded in
    `start()`. Without an injected store (fake backend) every credential op fails closed. A KEK
    re-wrap run counts `auth_keys`, the environment's auth keyring, and `export_keys`, its audit
    export signing keys, which boot opens or generates, and is never complete without both
    (#3505; #889). `loop_store` builds the order lane's own credential store; only M2 calls it."""
    sink = secrets_audit_sink(audit) if audit is not None else None
    if store is None or kcv_store is None:
        svc = SecretsService(audit=sink)  # no store: fail closed, but still audited (C-2.9)
    else:
        svc = SecretsService(
            store=store, kcv_store=kcv_store, audit=sink, auth_keys=auth_keys,
            export_keys=export_keys,
        )  # fmt: skip
    return secrets_bundle(svc, serving=audit, loop_store=loop_store)


def _serving_writer(audit: object) -> object:
    """The serving loop's audit writer behind its service, once started; else None."""
    return audit.writer if isinstance(audit, AuditService) and audit.is_active else None


def secrets_bundle(
    svc: SecretsService, *, serving: object = None, loop_store: LoopStoreFactory | None = None
) -> SecretsBundle:
    """Every capability of `svc`, each minted here: `build_secrets_service`'s, and a test's that
    builds a service of its own. `serving` is the serving loop's audit service: bound to that
    loop, `lane_signing` refuses it and its writer to the lane (#913 L3b), whose store M2 builds
    with `loop_store`, never the serving loop's (#913 L1d)."""
    bind = mint_loop_signing(svc, "exchange_adapter", loop_store=loop_store)

    def lane_signing(*, audit: LaneAuditWriter) -> LoopSigning:
        if audit is serving or audit is _serving_writer(serving):
            raise ValueError("the lane's audit writer is its own, never the serving loop's")
        return bind(_lane_audit_sink(audit))  # M2's sink, built here (C-2.9), over M2's store

    return SecretsBundle(
        SecretsLifecycleFacade(svc),
        SecretsMetadataFacade(svc),
        mint_borrower(svc, "exchange_adapter"),
        mint_candidate_keys(svc),
        _AuditExportSigner(mint_export_signer(svc)),
        _SigningKeyDirectory(mint_signing_keys(svc)),
        mint_signing_key_rotator(svc),
        mint_rotation_running(svc),
        lane_signing,
        mint_key_destroyer(svc),
    )


#: M2's export-signing refusals as the job's codes (22 `Job.error`), else `signing_unavailable`.
_SIGNING_FAILURES: Final = {
    "signing_key_rotated": "signing_key_rotated",
    "audit_unavailable": "audit_unavailable",
    "export_request_invalid": "internal_error",
}


class _AuditExportSigner:
    """`audit`'s `Signer` over M2's: an M2 refusal leaves as the job's code, nothing chained."""

    __slots__ = ("_signer",)

    def __init__(self, signer: ExportSigner) -> None:
        self._signer = signer

    @audited("security.audit_export_signed", "security.audit_export_sign_failed")  # M2 writes
    async def sign_audit_export(
        self, key_id: str, digest: bytes, job_id: uuid.UUID, actor_user_id: uuid.UUID
    ) -> bytes:
        try:
            return await self._signer.sign_audit_export(key_id, digest, job_id, actor_user_id)
        except SecretsError as exc:
            code = _SIGNING_FAILURES.get(str(exc), "signing_unavailable")
        raise ExportSigningFailed(code)  # after the handler: nothing chained


class _SigningKeyDirectory:
    """`audit`'s `SigningKeyDirectory` over M2's: public key material only."""

    __slots__ = ("_keys",)

    def __init__(self, keys: SigningKeys) -> None:
        self._keys = keys

    @audit_exempt("read")
    async def active(self) -> SigningKey | None:
        active = await self._keys.active()
        return None if active is None else SigningKey(*active)

    @audit_exempt("read")
    async def listing(self) -> list[dict[str, Any]] | None:
        return await self._keys.listing()


def build_audit_service(
    repository: AuditRepository | None = None, *, lane_keys: LaneKeyLoader | None = None
) -> AuditHandle:
    """Construct M19. No I/O. With a repository (storage_backend=real, QA
    #1658) `start()` wires the real WAL-backed `AuditWriter`; without one it
    stays the scaffold. `start()` runs `lane_keys`, the composition root's
    lane key loader, once (ADR-0037 decision 6)."""
    return AuditService(repository, lane_keys=lane_keys)


def build_audit_break_halt(
    audit: AuditService, *, unread: bool, on_change: Callable[[str | None], Awaitable[None]]
) -> AuditBreakHaltService:
    """The audit-chain break halt and its service (#2904), with no I/O: `unread` on the real
    backend, where nothing may trade until the lifespan's `start()` has read the chain; the fake
    backend runs no verifier, so its halt starts clear. `on_change` publishes each change of the
    halt's reason (None when clear) to the gateway's view of the kill switch."""
    return AuditBreakHaltService(AuditBreakHalt(unread=unread), audit, on_change=on_change)


def build_audit_verify_job(
    audit: AuditService, settings: Settings, metrics: Metrics, runner: VerifyRunner | None
) -> AuditVerifyJob | None:
    """The start-up and nightly verify job (#2111), or `None` while no runner is wired (nothing
    runs; in `live` the verify gauge stays 0 and `AuditVerifyNotPassing` pages). No I/O; the
    lifespan starts it once the audit module is up."""
    if runner is None:
        return None
    return AuditVerifyJob(
        runner,
        lambda: audit.query.verify_slot,
        metrics,
        hour_utc=settings.audit_verify_nightly_hour_utc,
        deadline_s=settings.audit_verify_nightly_deadline_s,
    )


def build_machine_event_sink(
    settings: Settings,
    store: MachineEventStore,
    *,
    metrics: SinkMetrics | None = None,
    wal_path: str | None = None,
) -> MachineEventSinkHandle:
    """The WAL-backed `machine_events` sink (E50-T63) over the composition root's events store
    adapter, its WAL at `wal_path`, else `settings.machine_event_wal_path` (beside the audit WAL
    unless set). No I/O: `start()` locks and opens the WAL."""
    return MachineEventWalSink(
        store,
        settings.machine_event_wal_path if wal_path is None else wal_path,
        max_bytes=settings.machine_event_wal_max_bytes,
        metrics=metrics,
    )


def unclaimed_machine_events(settings: Settings) -> int:
    """The bytes of frames `CV_MACHINE_EVENT_WAL_PATH` holds that Postgres has not taken, for the
    OMS runtime, which holds no sink of that file without a persistence bundle (#913 L2,
    SEC-S3L2-03) and may not import M19 (C-3.3): read under the file's lock, 0 with no file,
    `MachineEventSinkUnavailable` while another process holds it. Opens the WAL: run it off the
    loop."""
    return frames_left(settings.machine_event_wal_path, settings.machine_event_wal_max_bytes)


def build_lane_audit_writer(
    repository: AuditRepository,
    wal_path: str,
    *,
    on_alarm: Callable[[str], Awaitable[None]],
) -> AuditWriter:
    """The order lane's own `AuditWriter` (#913 slice 3 L2, 29 CV-C13), which the OMS runtime
    builds on the lane's loop over the OMS pool's audit repository, for the composition root,
    which may not import M19 (C-3.3). Its WAL at `wal_path` is its own, never the serving loop's:
    exclusive, it is locked before it is opened and until the end of the writer's stop (D6). Its
    records join the one `audit_log` chain, whose inserts the chain lock serialises (ruling
    Q12). Its fail-closed alarm (a refused append, its flusher's death) is `on_alarm`, the
    runtime's page (ruling 4), always given. Opens and scans its WAL, so the lane calls it, as
    `AuditService.start` builds the serving loop's on that loop."""
    return AuditWriter(repository, wal_path, on_alarm=on_alarm, exclusive=True)


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


def audit_writer_sink(
    writer: Any, *, acting: Callable[[str], str]
) -> Callable[[str, dict[str, str]], Awaitable[None]]:
    """Adapt `AuditWriter.emit` (durable, write-ahead) to the scope audit port. `acting` names the
    record's actor for the caller: the app passes `acting_user`, so a request viewing as the
    caller names the viewer (#3085, Q2), never the target the emitter's tripwire refuses."""
    names = {
        "rule_scope_denied": "rules.scope_denied",
        "rule_live_scope_armed": "rules.live_scope_armed",
        "rule_action_scope_denied": "rules.scope_denied",
    }

    async def sink(event: str, data: dict[str, str]) -> None:
        caller = data.get("caller")
        actor = None if caller is None else acting(caller)
        await writer.emit(
            names[event],
            actor_label=actor or "unknown",
            actor_user_id=actor,
            object_kind="rule_scope",
            object_id=data.get("account") or data.get("environment"),
            severity=Severity.ERROR if data.get("severity") == "high" else Severity.WARNING,
            before_state=_before(data),
            after_state={k: v for k, v in data.items() if k != "scope_before"},
            request_id=current_request_uuid(),
        )

    return sink
