"""Composition, as production composes it (#843 A4 brief items 1 and 2; `app.py` `_build_audit`,
`_build_secrets`, `build_app_context`), in the harness's own process and on its own loop.

1. `check_environment` and the audit WAL check (`safety.check_audit_dir`), before anything opens.
2. `prove_kek_possession` (the break-glass preflight): the KEK must already be enrolled, so this
   process's M2 start only opens what exists; it never enrols, audits or latches.
3. M19: `build_audit_service(repository)` with no lane key loader, so `start()` loads no lane
   key, takes no `lane.lock` and builds no lane (`audit/service.py`); the writer keeps its own WAL
   under `CV_AUDIT_WAL_PATH` (`Settings.audit_wal_path`), and Postgres serialises the chain
   (`pg_advisory_xact_lock(hashtext('audit_log'))` in the insert and in `audit_chain()`).
4. M2: `build_secrets_service(credentials, kcv, audit, auth_keys=..., export_keys=None)`. Start
   never opens the auth keyring (only a KEK re-wrap counts it), but with the export key store it
   may destroy retired seeds, generate a key or re-wrap one (`_export_custody.open_at_boot`), so
   the harness never passes it; with no previous KEK handle it loads one KEK and re-wraps nothing.
   Then its health must be OK and the harness's own gate unlatched.
5. `ExchangeBybitService(credentials=timed_borrower(bundle.exchange_borrower, timings),
   rest_transport=..., private_ws_connect=..., environment="demo").trading_port("demo",
   clock_offset_ms=...)`: the real port, signed by M2 under `sign_rest` and `sign_ws_auth`
   through a timing wrapper (`measure.timed_borrower`: each `sign` call timed, the call and its
   result untouched), offline over the in-memory M2 the same way. The harness names the key by
   its `api_keys.id` and never holds a secret.

`close` stops in reverse, the flatten having run first (`run.py`): the adapter's streams, the
ports, the transport, M2 (the KEK zeroed), then the audit writer, flushed into Postgres with what
is left in its WAL reported (never delete that volume before it drains, C-2.9), then the pools.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import httpx

from candleviewer.admin.wiring import (
    AuditHandle,
    SecretsBundle,
    build_audit_service,
    build_secrets_service,
    secrets_audit_row,
)
from candleviewer.exchange.bybit.key_ws_probe import PrivateWsConnect
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.exchange.bybit.trading import BybitTradingPort
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.observability.health import HealthStatus
from candleviewer.secrets import (
    AuthKeyStore,
    CredentialStore,
    KcvStore,
    KekCheckResult,
    prove_kek_possession,
)
from spike.oms_demo_path.measure import Timings, timed_borrower
from spike.oms_demo_path.safety import Refused, check_environment

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.audit.repository import AuditRepository
    from candleviewer.settings import Settings

#: `prove_kek_possession`'s shape (offline passes its `harden` seam).
Prove = Callable[["Settings", KcvStore], Awaitable[KekCheckResult]]
#: M2's construction: `build_secrets_service` online, the same over a harden seam offline.
BuildM2 = Callable[[CredentialStore, KcvStore, AuditHandle, AuthKeyStore | None], SecretsBundle]


def production_m2(
    store: CredentialStore, kcv: KcvStore, audit: AuditHandle, auth_keys: AuthKeyStore | None
) -> SecretsBundle:
    """As `app._build_secrets` builds it, without the export signing keys (see step 4)."""
    return build_secrets_service(store, kcv, audit, auth_keys=auth_keys, export_keys=None)


@dataclass
class Stores:
    credentials: CredentialStore
    kcv: KcvStore
    auth_keys: AuthKeyStore | None
    audit: AuditRepository
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)


def postgres_stores(settings: Settings) -> Stores:  # pragma: no cover - online only
    """The real stores, over the runtime DSN (`CV_PG_DSN`), never the owner's."""
    from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
    from candleviewer.storage.repositories.auth_keys_sqlalchemy import SqlAlchemyAuthKeyStore
    from candleviewer.storage.repositories.credentials_sqlalchemy import (
        SqlAlchemyCredentialStore,
    )
    from candleviewer.storage.repositories.relational_sqlalchemy import (
        SqlAlchemyRelationalRepository,
    )

    dsn = settings.pg_dsn.get_secret_value()
    env = settings.environment.value
    audit_rel = SqlAlchemyRelationalRepository(dsn, "spike-audit")
    secrets_rel = SqlAlchemyRelationalRepository(dsn, "spike-secrets")
    store = SqlAlchemyCredentialStore(secrets_rel, audit_row=secrets_audit_row(env))
    return Stores(
        credentials=store,
        kcv=store,
        auth_keys=SqlAlchemyAuthKeyStore(secrets_rel, env=settings.environment.value),
        audit=SqlAlchemyAuditRepository(
            audit_rel,
            read_slots=settings.audit_query_global_max_concurrent,
            verify_read_timeout_ms=settings.audit_verify_statement_timeout_ms,
            verify_max_entry_bytes=settings.audit_verify_max_entry_bytes,
        ),
        closers=[audit_rel.dispose, secrets_rel.dispose],
    )


@dataclass
class Composed:
    settings: Settings
    stores: Stores
    audit: AuditHandle
    bundle: SecretsBundle
    gate: ReadOnlyGate
    venue: ExchangeBybitService
    port: BybitTradingPort
    transport: httpx.AsyncBaseTransport
    timings: Timings
    ports: list[BybitTradingPort] = field(default_factory=list)
    kek_version: int | None = None

    def skewed_port(self, offset_ms: int) -> BybitTradingPort:
        """A port of the adapter's own factory signing on a clock `offset_ms` off (`10002`)."""
        port = self.venue.trading_port("demo", clock_offset_ms=lambda: offset_ms)
        self.ports.append(port)
        return port


def app_context(settings: Settings, gate: ReadOnlyGate) -> AppContext:
    """What `start(ctx)` reads (its settings and the order gate); typed `AppContext` only."""
    return cast("AppContext", SimpleNamespace(settings=settings, oms_read_only_gate=gate))


async def compose(
    settings: Settings,
    stores: Stores,
    *,
    rest_transport: httpx.AsyncBaseTransport,
    private_ws_connect: PrivateWsConnect,
    clock_offset_ms: Callable[[], int | None],
    build_m2: BuildM2 = production_m2,
    prove: Prove = prove_kek_possession,
    timings: Timings | None = None,
) -> Composed:
    """Steps 1 to 5 of the module docstring; `timings` takes the signing times (a fresh one by
    default: the borrower is wrapped either way)."""
    check_environment(settings)
    if settings.kek_prev_handle:
        raise Refused("a previous KEK handle is set (a rotation window): the harness waits")
    proof = await prove(settings, stores.kcv)
    if not proof.kcv_ok or proof.version != settings.kek_version:
        raise Refused(f"the KEK proof failed ({proof.reason}): boot cv-api on it first")
    audit = build_audit_service(stores.audit)
    bundle = build_m2(stores.credentials, stores.kcv, audit, stores.auth_keys)
    gate = ReadOnlyGate()
    ctx = app_context(settings, gate)
    await audit.start(ctx)
    try:
        await bundle.lifecycle.start(ctx)
        health = bundle.lifecycle.health()
        if health.status is not HealthStatus.OK or gate.is_read_only:
            raise Refused(f"M2 did not come up clean ({health.detail or health.status.value})")
    except BaseException:
        await bundle.lifecycle.stop(5.0)
        await audit.stop(5.0)
        raise
    timed = Timings() if timings is None else timings
    venue = ExchangeBybitService(
        credentials=timed_borrower(bundle.exchange_borrower, timed),
        rest_transport=rest_transport,
        private_ws_connect=private_ws_connect,
        environment="demo",
    )
    port = venue.trading_port("demo", clock_offset_ms=clock_offset_ms)
    return Composed(
        settings=settings,
        stores=stores,
        audit=audit,
        bundle=bundle,
        gate=gate,
        venue=venue,
        port=port,
        transport=rest_transport,
        timings=timed,
        ports=[port],
        kek_version=proof.version,
    )


async def close(composed: Composed, grace_s: float = 10.0) -> dict[str, Any]:
    """Teardown in reverse (see the module docstring); returns what the audit writer reports."""
    report: dict[str, Any] = {}
    await composed.venue.stop(grace_s)
    for port in composed.ports:
        await port.aclose()
    await composed.transport.aclose()
    await composed.bundle.lifecycle.stop(grace_s)
    audit = composed.audit
    if audit.is_active:
        writer = audit.writer
        try:
            await writer.flush(grace_s)
        except TimeoutError:
            report["flush"] = "timed_out"
        report |= {"written": writer.written_total, "buffer_depth": writer.buffer_depth}
    await audit.stop(grace_s)
    for closer in composed.stores.closers:
        await closer()
    return report
