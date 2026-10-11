"""Lifecycle for the secrets module (M2): KEK load, fail-closed degraded mode (e27-kek.md §6).

`start()` resolves the KEK source (a `file` source in live is fatal, `KekSourceNotPermitted`),
loads the KEK, checks its KCV in constant time and builds the broker. Any load failure
leaves the module DEGRADED: health reports the reason, a sticky latch on the process
read-only gate refuses order placement and publishes the `system` notice, the
failure metric increments (critical alert) and every credential operation raises
`KekUnavailable`. There is no runtime re-load; recovery is a launcher restart.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

import structlog

from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.secrets import _kek
from candleviewer.secrets import _metrics as m
from candleviewer.secrets.broker import CredentialBroker
from candleviewer.secrets.errors import KekLoadError, KekUnavailable
from candleviewer.secrets.models import KekCheckResult, RewrapReport
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.store import AuditSink, CredentialStore

if TYPE_CHECKING:
    from candleviewer.app import AppContext

REMEDIATION = (
    "KEK unavailable (reason={reason}): trading disabled. Ensure the host launcher/systemd "
    "credential supplies CV_KEK_HANDLE, then restart cv-api via the launcher. "
    "See docs/ops/runbooks/kek-custody.md."
)


def _log() -> Any:
    return structlog.get_logger(__name__)


class KcvStore(Protocol):
    async def kcv_for(self, version: int) -> bytes | None: ...
    async def record_kcv(self, version: int, kcv: bytes) -> None: ...


class LatchableGate(Protocol):
    def latch(self, *, reason_code: str, reason_text: str) -> None: ...


SourceFactory = Callable[..., _kek.KekSource]


class SecretsService:
    def __init__(
        self,
        *,
        store: CredentialStore | None = None,
        kcv_store: KcvStore | None = None,
        audit: AuditSink | None = None,
        source_factory: SourceFactory = _kek.source_from_settings,
        harden: Callable[[], None] = _kek.harden_process,
    ) -> None:
        self._harden = harden
        self._store, self._kcv, self._audit_sink = store, kcv_store, audit
        self._source_factory = source_factory
        self._broker: CredentialBroker | None = None
        self._kek_version: int | None = None
        self._reason: str | None = None
        self._started = False

    async def _audit(self, action: str, fields: dict[str, str]) -> None:
        if self._audit_sink is None:
            raise KekUnavailable("audit_unavailable")
        await self._audit_sink(action, fields)

    async def start(self, ctx: AppContext) -> None:
        settings = ctx.settings
        source = self._source_factory(settings)  # KekSourceNotPermitted propagates: fatal
        if self._store is None:
            # Fake storage backend: nothing to protect, broker disabled (ops fail closed).
            # In live this is still a degraded, trading-blocked state.
            self._reason, self._started = "no_credential_store", True
            if settings.environment.value == "live":
                await self._degrade(ctx, "no_credential_store")
            return
        self._harden()
        started = time.perf_counter()
        kek: _kek.LoadedKek | None = None
        prev: _kek.LoadedKek | None = None
        try:
            kek = source.load()
            await self._check_kcv(kek)
            if settings.kek_prev_handle:
                prev = self._source_factory(settings, previous=True).load()
                await self._check_kcv(prev)
        except KekLoadError as exc:
            for k in (kek, prev):
                if k is not None:
                    k.close()
            await self._degrade(ctx, exc.reason)
        else:
            m.kek_load_seconds.observe(time.perf_counter() - started)
            m.kek_version.set(kek.version)
            self._kek_version = kek.version
            self._broker = CredentialBroker(
                self._store,
                self._audit,
                kek,
                prev_kek=prev,
                dek_cache_ttl_s=settings.dek_cache_ttl_s,
            )
            await self._audit("security.kek_loaded", {"kek_version": str(kek.version)})
        self._started = True

    async def _check_kcv(self, kek: _kek.LoadedKek) -> None:
        if self._kcv is None:
            return
        expected = await self._kcv.kcv_for(kek.version)
        if expected is None:
            await self._kcv.record_kcv(kek.version, kek.kcv())
        elif not _kek.kcv_matches(kek, expected):
            raise KekLoadError("kek_mismatch")

    async def _degrade(self, ctx: AppContext, reason: str) -> None:
        self._reason = reason
        m.kek_load_failures_total.labels(reason=reason).inc()
        m.kek_version.set(0)
        text = REMEDIATION.format(reason=reason)
        _log().critical("secrets.kek_unavailable", reason=reason, remediation=text)
        gate: LatchableGate = ctx.oms_read_only_gate
        gate.latch(reason_code="secrets.kek_unavailable", reason_text=text)
        try:
            await self._audit("security.kek_load_failed", {"reason": reason})
        except Exception:  # audit outage must not un-degrade; already fail closed
            _log().exception("secrets.kek_load_failed_audit_error", reason=reason)

    async def lose_kek(self, ctx: AppContext, reason: str = "kek_unavailable") -> None:
        """Runtime loss (chaos): zero all key material and degrade; no stale plaintext."""
        if self._broker is not None:
            self._broker.drop_kek()
        self._broker = None
        self._kek_version = None
        await self._degrade(ctx, reason)

    @property
    def broker(self) -> CredentialBroker:
        if self._broker is None:
            raise KekUnavailable("kek_unavailable")
        return self._broker

    async def with_credentials[T](
        self,
        key_id: UUID,
        fn: Callable[[Secret[str], Secret[str]], Awaitable[T]],
        *,
        caller_module: str,
        purpose: str,
    ) -> T:
        return await self.broker.with_credentials(
            key_id, fn, caller_module=caller_module, purpose=purpose
        )

    async def verify_kek_possession(self) -> KekCheckResult:
        """Metadata only, for `admin` (C-3.2)."""
        if self._broker is None:
            return KekCheckResult(None, False, self._reason or "kek_unavailable")
        return KekCheckResult(self._kek_version, True, None)

    async def rewrap_deks(self, to_version: int) -> RewrapReport:
        """Counts only, for `admin` (C-3.2)."""
        return await self.broker.rewrap_all(to_version)

    async def stop(self, grace_s: float) -> None:
        if self._broker is not None:
            self._broker.drop_kek()
        self._broker = None
        self._started = False

    def health(self) -> HealthReport:
        if not self._started:
            return HealthReport(module="secrets", status=HealthStatus.STOPPED)
        if self._broker is None:
            return HealthReport(
                module="secrets", status=HealthStatus.DEGRADED, detail=self._reason or ""
            )
        return HealthReport(module="secrets", status=HealthStatus.OK)
