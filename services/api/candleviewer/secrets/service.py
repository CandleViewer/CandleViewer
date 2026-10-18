"""Lifecycle for the secrets module (M2): KEK load, fail-closed degraded mode (e27-kek.md §6).

`start()` latches the process read-only gate *first* on any failure (the only enforcement
step), then records metric/log/audit. A KEK is published only after: process hardening
(checked; live fails closed), an off-loop load under a timeout (a late load from an abandoned
worker is zeroed), the FIFO nonce-ack written once every handle is drained, the KEK version
policy (no reused/retired/out-of-sequence KEK), a KCV check without trust-on-first-use (the
previous KEK first, #2266), the count of stranded rows (latched, but the broker is kept), and
a successful `security.kek_loaded` audit. No runtime re-load; recovery is a restart.

Capabilities (C-3.2): `AppContext.secrets` is `SecretsLifecycle` (start/stop/health only);
`admin` is injected `SecretsMetadata`; the M4 signing capability is minted once in
`admin.wiring` (`SecretsBundle.exchange_borrower`) — callers never declare their identity.
It returns a MAC and the key id, never the API secret (C-2.7, #2339). The offline break-glass
proof (`prove_kek_possession`, admin only, #2119) shares the custody path but never enrols.
Key import's `CandidateKeys` (#836, `SecretsBundle.candidate_keys`) is minted in wiring too.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, final
from uuid import UUID

import structlog

from candleviewer.observability.context import spawn
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.secrets import _kek, _source
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._rotation import RotatingBroker
from candleviewer.secrets.broker import ALLOWED_CALLERS, Purpose, _m2_only
from candleviewer.secrets.candidate import CANDIDATE_HOLD_S, CandidateKeys, hold_candidate
from candleviewer.secrets.errors import (
    CredentialUnavailable,
    KekLoadError,
    KekRotationError,
    KekSourceNotPermitted,
    KekUnavailable,
    RotationCode,
)
from candleviewer.secrets.models import KekCheckResult, RewrapReport, StoredCredential
from candleviewer.secrets.signing import RequestSignature, SigningMessage
from candleviewer.secrets.store import AuditSink, AuthKeyStore, CredentialStore, KcvStore

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.settings import Settings

REMEDIATION = (
    "KEK unavailable (reason={reason}): trading disabled. Ensure the host launcher/systemd "
    "credential supplies CV_KEK_HANDLE, then restart cv-api via the launcher. "
    "See docs/ops/runbooks/kek-custody.md."
)
GATE_REASON = "secrets.kek_unavailable"
#: #2266: a boot that left unrevoked API key rows at a KEK version it did not load.
STRANDED_GATE_REASON = "secrets.kek_rows_stranded"
STRANDED_REMEDIATION = (
    "KEK rows stranded: API keys of this environment are wrapped under a KEK version this "
    "process did not load, so they cannot sign; new orders are disabled. Restart cv-api via the "
    "launcher with CV_KEK_PREV_HANDLE supplying the previous KEK and finish the re-wrap, or, if "
    "that KEK is lost, revoke those keys at the exchange and in CandleViewer, then restart. "
    "See docs/ops/runbooks/kek-custody.md."
)
#: #2266: a KEK re-wrap run latched order entry before its first row, until the restart.
ROTATION_GATE_REASON = "secrets.kek_rotation"
ROTATION_REMEDIATION = (
    "KEK rotation: a re-wrap run latched order entry read-only before its first row; new orders "
    "stay disabled until the restart that ends the rotation. Cancels and stop-loss amendments "
    "keep signing. See docs/ops/runbooks/kek-custody.md."
)
#: The broker's reasons for a record it could not write (`CredentialBroker._audit`).
_AUDIT_FAILURES = frozenset({"audit_unavailable", "audit_timeout"})
#: Bounded `reason` label values of `cv_kek_load_failures_total` (pre-initialised at 0).
REASONS = (
    "kek_unavailable",
    "kek_mismatch",
    "kek_handle_permissions",
    "kek_reused",
    "kek_retired",
    "kek_version_out_of_sequence",
    "process_hardening_failed",
    "kcv_store_unavailable",
    "audit_unavailable",
    "no_credential_store",
    "kek_rows_stranded",
)
_LOAD_MARGIN_S = 5.0
_AUDIT_TIMEOUT_S = 2.0


def _log() -> Any:
    return structlog.get_logger(__name__)


for _r in REASONS:
    m.kek_load_failures_total.labels(reason=_r)


class LatchableGate(Protocol):
    def latch(self, *, reason_code: str, reason_text: str) -> None: ...


class SecretsMetadata(Protocol):
    """The only M2 surface `admin` (M21) may hold: metadata, no bytes, no borrow (C-3.2)."""

    async def verify_kek_possession(self) -> KekCheckResult: ...
    async def rewrap_deks(
        self, to_version: int, *, environment: str, actor_user_id: str, actor_role: str
    ) -> RewrapReport: ...


class SecretsLifecycle(Protocol):
    """What the supervisor / every `AppContext` holder sees: lifecycle + health only."""

    async def start(self, ctx: AppContext) -> None: ...
    async def stop(self, grace_s: float) -> None: ...
    def health(self) -> HealthReport: ...


class SigningCapability(Protocol):
    """What the exchange adapter signs with (C-2.7): the stored-key `CredentialBorrower` or a
    candidate key's `CandidateSigner` (#836). M2 MACs `message` and returns the key id and the hex
    MAC, never the API secret."""

    async def sign(
        self, key_id: UUID, message: SigningMessage, *, purpose: Purpose
    ) -> RequestSignature: ...


def _sealed_borrower(resolve: Callable[[], RotatingBroker], caller: str) -> CredentialBorrower:
    """Build a signer whose broker resolver lives only in a closure (no attribute to reach)."""
    if caller not in ALLOWED_CALLERS:
        raise ValueError("caller not permitted to borrow credentials")

    async def sign(key_id: UUID, message: SigningMessage, purpose: Purpose) -> RequestSignature:
        return await resolve().borrow_handle(caller).sign(key_id, message, purpose=purpose)

    return CredentialBorrower(sign)


@final
class CredentialBorrower:
    """Caller-bound signing capability, minted once at wiring time for M4. M2 computes the
    request MAC; the capability returns the hex MAC and the key id, never the API secret
    (C-2.7, #2339). Holds only a closure: no reference to the service or broker is reachable
    from it (C-3.2)."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("__borrow",)

    def __init__(self, borrow: Callable[..., Awaitable[RequestSignature]]) -> None:
        self.__borrow = borrow

    async def sign(
        self, key_id: UUID, message: SigningMessage, *, purpose: Purpose
    ) -> RequestSignature:
        """Sign `message` (byte segments, `KEY_ID_SLOT` where the key id goes) with the
        credential's API secret inside M2; audited write-ahead as `credential_borrowed`."""
        return await self.__borrow(key_id, message, purpose)


class SecretsLifecycleFacade:
    """What `AppContext.secrets` holds: start/stop/health only. Closures, no service field."""

    __slots__ = ("health", "start", "stop")

    def __init__(self, svc: SecretsService) -> None:
        async def start(ctx: AppContext) -> None:
            await svc.start(ctx)

        async def stop(grace_s: float) -> None:
            await svc.stop(grace_s)

        def health() -> HealthReport:
            return svc.health()

        self.start, self.stop, self.health = start, stop, health


class SecretsMetadataFacade:
    """What `admin` holds (C-3.2 "M21 only for metadata"): verify + counts-only re-wrap."""

    __slots__ = ("rewrap_deks", "verify_kek_possession")

    def __init__(self, svc: SecretsService) -> None:
        async def verify_kek_possession() -> KekCheckResult:
            return await svc.verify_kek_possession()

        async def rewrap_deks(
            to_version: int, *, environment: str, actor_user_id: str, actor_role: str
        ) -> RewrapReport:
            return await svc.rewrap_deks(
                to_version,
                environment=environment,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
            )

        self.verify_kek_possession, self.rewrap_deks = verify_kek_possession, rewrap_deks


@final
class SecretsService:
    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    def __init__(
        self,
        *,
        store: CredentialStore | None = None,
        kcv_store: KcvStore | None = None,
        audit: AuditSink | None = None,
        sources: Callable[[Any], _source.KekSources] = _source.sources_from_settings,
        harden: Callable[[], bool] = _kek.harden_process,
        load_timeout_s: float = 10.0 + _LOAD_MARGIN_S,
        auth_keys: AuthKeyStore | None = None,
    ) -> None:
        self._store, self._kcv, self._audit_sink = store, kcv_store, audit
        self._sources, self._harden = sources, harden
        self._load_timeout = load_timeout_s
        #: The environment's auth keyring rows a re-wrap run counts (#3505).
        self._auth_keys = auth_keys
        self._broker: RotatingBroker | None = None
        self._kek_version: int | None = None
        self._reason: str | None = None
        self._latched = False
        self._started = False
        #: Captured at `start()`: what a re-wrap run latches, and the one environment it serves.
        self._gate: LatchableGate | None = None
        self._env = ""
        #: The single-flight lock of this environment's re-wrap runs (#2266).
        self._rotating = False

    async def _audit(self, action: str, fields: dict[str, str]) -> None:
        if self._audit_sink is None:
            raise KekLoadError("audit_unavailable")
        try:
            async with asyncio.timeout(_AUDIT_TIMEOUT_S):
                await self._audit_sink(action, {"actor_kind": "system", "actor_role": "secrets",
                                                **fields})  # fmt: skip
        except Exception:
            raise KekLoadError("audit_unavailable") from None

    async def _load(self, source: _kek.KekSource) -> _kek.LoadedKek:
        """Worker-thread load; on timeout/cancel the late result is zeroed, never leaked."""
        abandoned = getattr(source, "abandoned", None)
        fut = spawn(asyncio.to_thread(source.load), name="secrets-kek-load")

        def reap(f: asyncio.Future[_kek.LoadedKek]) -> None:
            if not f.cancelled() and f.exception() is None:
                f.result().close()

        try:
            async with asyncio.timeout(self._load_timeout):
                return await asyncio.shield(fut)
        except BaseException as exc:
            if abandoned is not None:
                abandoned.set()
            fut.add_done_callback(reap)
            if isinstance(exc, TimeoutError):
                raise KekLoadError("kek_unavailable") from None
            raise

    async def _bounded[T](self, aw: Awaitable[T]) -> T:
        """Every boot-time thread offload is bounded; a hang becomes `kek_unavailable`."""
        try:
            async with asyncio.timeout(self._load_timeout):
                return await aw
        except TimeoutError:
            raise KekLoadError("kek_unavailable") from None

    async def _check_versions(
        self, env_name: str, kek: _kek.LoadedKek, prev: _kek.LoadedKek | None
    ) -> dict[int, tuple[bytes, bool]]:
        """Version policy, per environment lineage (#2338): no KCV reused across versions or
        environments, no retired KEK, current is max or max+1 (then prev must be max). Returns
        the `env_name` lineage's `kek_versions` rows it checked against, keyed by version."""
        if self._kcv is None:  # pragma: no cover - start() checked
            raise KekLoadError("kcv_store_unavailable")
        try:
            async with asyncio.timeout(_AUDIT_TIMEOUT_S):
                rows = await self._kcv.kcv_versions()
        except Exception:
            raise KekLoadError("kcv_store_unavailable") from None
        known = {v: (kcv, retired) for e, v, kcv, retired in rows if e == env_name}
        for k in filter(None, (kek, prev)):
            if any(
                (e, v) != (env_name, k.version) and _kek.kcv_matches(k, kcv)
                for e, v, kcv, _ in rows
            ):
                raise KekLoadError("kek_reused")
            if known.get(k.version, (b"", False))[1]:
                raise KekLoadError("kek_retired")
        top = max(known, default=0)
        ok = kek.version == top or (
            kek.version == top + 1 and (top == 0 or (prev is not None and prev.version == top))
        )
        if not ok:
            raise KekLoadError("kek_version_out_of_sequence")
        return known

    async def _acquire_keks(
        self, settings: Settings, srcs: _source.KekSources, held: list[_kek.LoadedKek]
    ) -> tuple[_kek.LoadedKek, _kek.LoadedKek | None]:
        """The custody path `start()` and the break-glass proof share: SR-009 hardening (fatal
        in live), the handoff nonce read before any FIFO opens, every handle drained in order,
        one ack after the last. Each KEK joins `held` once loaded; the caller zeroes them."""
        live = settings.environment.value == "live"
        hardened = await self._bounded(asyncio.to_thread(self._harden))
        if not hardened:
            m.process_hardening_failures_total.inc()
            _log().warning("secrets.process_hardening_failed", live=live)
            if live:
                raise KekLoadError("process_hardening_failed")
        nonce = None
        handles = [p for p in (settings.kek_handle, settings.kek_prev_handle) if p]
        if srcs.ack_path is not None and any(map(_kek.is_fifo, handles)):
            # before any FIFO is opened (the launcher unlinks the handoff dir afterwards)
            handoff = Path(settings.kek_handle).parent
            nonce = await self._bounded(asyncio.to_thread(_kek.read_handoff, handoff))
        kek = await self._load(srcs.current)
        held.append(kek)
        prev = None
        if srcs.previous is not None:
            prev = await self._load(srcs.previous)
            held.append(prev)
        fifo = kek.is_fifo or (prev is not None and prev.is_fifo)
        if live and fifo and nonce is None:
            raise KekLoadError("kek_handle_permissions")
        if fifo and nonce is not None and srcs.ack_path is not None:
            await self._bounded(asyncio.to_thread(_kek.write_ack, nonce, srcs.ack_path))
        return kek, prev

    async def start(self, ctx: AppContext) -> None:
        settings = ctx.settings
        env_name = settings.environment.value
        live = env_name == "live"
        srcs = self._sources(settings)  # KekSourceNotPermitted propagates: fatal
        self._started = True
        self._gate, self._env = ctx.oms_read_only_gate, env_name
        if self._store is None or self._kcv is None:
            self._reason = "no_credential_store"
            if live:
                await self._degrade(ctx, "no_credential_store")
            return
        held: list[_kek.LoadedKek] = []
        started = time.perf_counter()
        try:
            kek, prev = await self._acquire_keks(settings, srcs, held)
            await self._check_versions(env_name, kek, prev)
            broker = RotatingBroker(
                self._store, self._audit, kek, prev_kek=prev,
                dek_cache_ttl_s=settings.dek_cache_ttl_s, env_name=settings.environment.value,
            )  # fmt: skip
            try:  # #2266: the previous KEK first, so a wrong one never pins v(n+1)
                if prev is not None:
                    await broker.verify_kcv(prev, self._kcv, must_exist=True)
                await broker.verify_kcv(kek, self._kcv, must_exist=False)
            except KekLoadError:
                raise
            except Exception:
                raise KekLoadError("kcv_store_unavailable") from None
            try:  # #2266: unrevoked rows at a KEK version not loaded; unreadable fails closed
                async with asyncio.timeout(_AUDIT_TIMEOUT_S):
                    loaded = (k.version for k in held)
                    stranded = await self._store.count_stranded(env_name, *loaded)
            except Exception:
                raise KekLoadError("kcv_store_unavailable") from None
            fields = {"env": env_name, "kek_version": str(kek.version), "kcv": kek.kcv().hex()}
            await self._audit("security.kek_loaded", fields)
            if stranded:
                await self._strand(ctx, kek.version, stranded)
        except GeneratorExit:
            self._close(*held)
            self._latch(ctx, "kek_unavailable")
            raise
        except BaseException as exc:
            self._close(*held)
            if isinstance(exc, KekSourceNotPermitted):
                raise
            if not isinstance(exc, Exception):  # cancelled boot: latch, no failure audit
                self._latch(ctx, "kek_unavailable")
                raise
            reason = exc.reason if isinstance(exc, KekLoadError) else "kek_unavailable"
            await self._degrade(ctx, reason)
            return
        m.kek_load_seconds.observe(time.perf_counter() - started)
        m.kek_version.set(kek.version)
        self._kek_version = kek.version
        self._broker = broker

    @staticmethod
    def _close(*keks: _kek.LoadedKek) -> None:
        for k in keks:
            k.close()

    async def _strand(self, ctx: AppContext, version: int, stranded: int) -> None:
        """#2266 item 5: the latch first, then the page and the record; `start()` then publishes
        the broker: stranded keys fail closed, the others sign, `destroy` needs no KEK."""
        self._latch(ctx, "kek_rows_stranded", code=STRANDED_GATE_REASON, text=STRANDED_REMEDIATION)
        m.kek_load_failures_total.labels(reason="kek_rows_stranded").inc()
        _log().critical(
            "secrets.kek_rows_stranded",
            stranded=stranded,
            kek_version=version,
            remediation=STRANDED_REMEDIATION,
        )
        fields = {"env": ctx.settings.environment.value, "kek_version": str(version)}
        await self._audit("security.kek_rows_stranded", {**fields, "stranded": str(stranded)})

    def _latch(
        self, ctx: AppContext, reason: str, *, code: str = GATE_REASON, text: str = ""
    ) -> str:
        text = text or REMEDIATION.format(reason=reason)
        gate: LatchableGate = ctx.oms_read_only_gate
        gate.latch(reason_code=code, reason_text=text)
        self._reason, self._latched = reason, True
        m.kek_degraded_state.set(1)
        return text

    async def _degrade(self, ctx: AppContext, reason: str) -> None:
        text = self._latch(ctx, reason)  # enforcement first; nothing below may skip it
        m.kek_load_failures_total.labels(reason=reason).inc()
        m.kek_version.set(0)
        _log().critical("secrets.kek_unavailable", reason=reason, remediation=text)
        try:
            fields = {"reason": reason, "env": ctx.settings.environment.value}
            await self._audit("security.kek_load_failed", fields)
        except Exception:  # audit outage must not un-degrade; already fail closed
            _log().exception("secrets.kek_load_failed_audit_error", reason=reason)

    def _require(self) -> RotatingBroker:
        if self._broker is None:
            raise KekUnavailable("kek_unavailable")
        return self._broker

    async def verify_kek_possession(self) -> KekCheckResult:
        """Metadata only, for `admin` (C-3.2)."""
        if self._broker is None:
            return KekCheckResult(None, False, self._reason or "kek_unavailable")
        return KekCheckResult(self._kek_version, True, self._reason)  # `kek_rows_stranded`

    async def _prove_possession(self, settings: Settings) -> KekCheckResult:
        """`prove_kek_possession`: the shared custody path, then a KCV check that never enrols."""
        held: list[_kek.LoadedKek] = []
        try:
            kek, prev = await self._acquire_keks(settings, self._sources(settings), held)
            known = await self._check_versions(settings.environment.value, kek, prev)
            for k in held:
                if k.version not in known:
                    raise KekLoadError("kek_not_enrolled")
                if not _kek.kcv_matches(k, known[k.version][0]):
                    raise KekLoadError("kek_mismatch")
        except KekSourceNotPermitted as exc:
            return KekCheckResult(None, False, exc.code)
        except KekLoadError as exc:
            return KekCheckResult(None, False, exc.reason)
        except Exception:  # fail closed; the detail may name a host path, so it is dropped
            return KekCheckResult(None, False, "kek_unavailable")
        finally:
            self._close(*held)
        return KekCheckResult(kek.version, True, None)

    async def rewrap_deks(
        self, to_version: int, *, environment: str, actor_user_id: str, actor_role: str
    ) -> RewrapReport:
        """Counts only, for `admin` (C-3.2), in the boot staged for this rotation (#2266 D1).

        Refused, audited (`security.kek_rotation_refused`) and with nothing latched or moved:
        `KekUnavailable` without a usable KEK, `kek_rotation_not_staged` unless `environment` is
        this process's and its KEKs are at `to_version` and `to_version - 1`, and
        `kek_rotation_in_progress` while a run is under way. Otherwise order entry is latched
        before the run's opening record, until restart, and the run counts the auth keyring
        (#3505). The Owner is recorded on every record."""
        actor = ("user", actor_role, actor_user_id)
        broker, gate = self._broker, self._gate
        if broker is None or gate is None:
            await self._refuse("kek_unavailable", actor, environment, to_version)
            raise KekUnavailable("kek_unavailable")
        try:
            broker.staged(to_version)
            staged = environment == self._env
        except (KekUnavailable, KekLoadError):
            staged = False
        code: RotationCode | None = None if staged else "kek_rotation_not_staged"
        if code is None and self._rotating:
            code = "kek_rotation_in_progress"
        if code is not None:
            await self._refuse(code, actor, environment, to_version)
            raise KekRotationError(code)
        self._rotating = True  # no await since the check: single-flight
        try:
            self._latch_rotation(gate)
            return await broker.rewrap_all(to_version, actor=actor, auth_keys=self._auth_keys)
        except CredentialUnavailable as exc:
            audit = str(exc) in _AUDIT_FAILURES
            raise KekRotationError("audit_unavailable" if audit else "store_unavailable") from None
        finally:
            self._rotating = False

    async def _refuse(
        self, code: str, actor: tuple[str, str, str], environment: str, to_version: int
    ) -> None:
        """A refusal's record, written before the refusal leaves (C-2.9); one that cannot be
        written answers `audit_unavailable` instead. Never latches."""
        kind, role, user = actor
        fields = {"actor_kind": kind, "actor_role": role, "actor_user_id": user, "env": self._env}
        fields |= {"reason": code, "to_version": str(to_version)}
        fields["requested_env"] = environment[:16]  # caller text, bounded (the route's is an enum)
        try:
            await self._audit("security.kek_rotation_refused", fields)
        except KekLoadError:
            raise KekRotationError("audit_unavailable") from None

    def _latch_rotation(self, gate: LatchableGate) -> None:
        """#2266: order entry read-only for the rest of this process. Health reads DEGRADED
        (`kek_rotation`, unless a boot latched first); no KEK page (`cv_kek_degraded_state`)."""
        gate.latch(reason_code=ROTATION_GATE_REASON, reason_text=ROTATION_REMEDIATION)
        self._reason, self._latched = self._reason or "kek_rotation", True
        _log().warning("secrets.kek_rotation_latched", remediation=ROTATION_REMEDIATION)

    async def stop(self, grace_s: float) -> None:
        broker, self._broker = self._broker, None
        self._started = False
        if broker is not None:
            broker.drop_kek()  # zeroed first, so a slow drain below can never delay it
            await broker.aclose()  # #2776: cancel and await its in-flight `last_used_at` writes

    def health(self) -> HealthReport:
        if not self._started:
            return HealthReport(module="secrets", status=HealthStatus.STOPPED)
        if self._broker is None and not self._latched:
            # Fake backend outside live: no credential store deployed; ops still fail closed.
            return HealthReport(
                module="secrets", status=HealthStatus.STOPPED, detail=self._reason or ""
            )
        if self._broker is None or self._latched:  # stranded rows keep the broker (#2266)
            return HealthReport(
                module="secrets", status=HealthStatus.DEGRADED, detail=self._reason or ""
            )
        return HealthReport(module="secrets", status=HealthStatus.OK)


def mint_borrower(service: SecretsService, caller_module: str) -> CredentialBorrower:
    """Wiring-time signing capability bound to `caller_module`. Called once, in
    `admin.wiring.build_secrets_service`; fails closed while degraded."""
    return _sealed_borrower(service._require, caller_module)


def mint_candidate_keys(
    service: SecretsService, *, hold_s: float = CANDIDATE_HOLD_S
) -> CandidateKeys:
    """Wiring-time key-import capability (#836): the candidate signer it hands out is bound to
    the exchange adapter, and each hold lasts at most `hold_s`. Called once, in
    `admin.wiring.build_secrets_service`; fails closed while degraded."""
    if not 0 < hold_s <= CANDIDATE_HOLD_S:
        raise ValueError("a candidate is held for at most CANDIDATE_HOLD_S")
    resolve, caller = service._require, "exchange_adapter"

    async def run(*args: Any) -> StoredCredential | None:
        return await hold_candidate(resolve(), caller, hold_s, *args)

    return CandidateKeys(run)


async def prove_kek_possession(
    settings: Settings,
    kcv_store: KcvStore,
    *,
    sources: Callable[[Any], _source.KekSources] = _source.sources_from_settings,
    harden: Callable[[], bool] = _kek.harden_process,
    load_timeout_s: float = 10.0 + _LOAD_MARGIN_S,
) -> KekCheckResult:
    """Offline break-glass proof of KEK possession (E09-S11 #2119, decision O1); `admin` only.

    Runs `start()`'s custody path in the calling process, then requires the KCV of every KEK
    supplied to be enrolled already in the `kek_versions` lineage of `settings.environment`
    (#2338; a KEK enrolled for another environment is `kek_reused`, as at boot): an unknown one
    is `kek_not_enrolled` in every environment (where `start()` would enrol it). Metadata only:
    nothing is enrolled, audited, latched or published (the caller audits), and every KEK
    loaded is zeroed before this returns. Refusals come back as `reason`, never raised;
    cancellation propagates. `sources`, `harden` and `load_timeout_s` are the `SecretsService`
    seams.
    """
    svc = SecretsService(
        kcv_store=kcv_store, sources=sources, harden=harden, load_timeout_s=load_timeout_s
    )
    return await svc._prove_possession(settings)
