"""Lifecycle for the secrets module (M2): KEK load, fail-closed degraded mode (e27-kek.md §6).

`start()` latches the process read-only gate *first* on any failure (the only enforcement
step), then records metric/log/audit. A KEK is published only after: process hardening
(checked; live fails closed), an off-loop load under a timeout (a late load from an abandoned
worker is zeroed), the FIFO nonce-ack written once every handle is drained, the KEK version
policy (no reused/retired/out-of-sequence KEK), a KCV check without trust-on-first-use (the
previous KEK first, #2266), the count of stranded rows (latched, but the broker is kept), and
a successful `security.kek_loaded` audit. No runtime re-load; recovery is a restart. Then the
audit export signing key is opened, or generated when the environment has none (#889,
`_export_custody`): a failure degrades `secrets` and pages but latches nothing (ADR-0039).

Capabilities (C-3.2): `AppContext.secrets` is `SecretsLifecycle` (start/stop/health only);
`admin` is injected `SecretsMetadata`; the M4 signing capability is minted once in
`admin.wiring` (`SecretsBundle.exchange_borrower`) — callers never declare their identity.
It returns a MAC and the key id, never the API secret (C-2.7, #2339). The offline break-glass
proof (`prove_kek_possession`, admin only, #2119) shares the custody path but never enrols.
Key import's `CandidateKeys` (#836, `SecretsBundle.candidate_keys`) is minted in wiring too, as
are the audit export's `ExportSigner` and `SigningKeys` (#889): a signature and public key
material, never a seed. So is `SigningKeyRotator` (#889 S7), the signing key's rotation for
`admin`, which answers with public key material and, once its new key passes the check, makes
export available again with no restart, and `RotationRunning` (#889 S10), which tells the export
route only whether a rotation runs. `mint_loop_signing` (#913 L3b) binds signing to the order lane.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NoReturn, Protocol, final
from uuid import UUID

import structlog

from candleviewer.observability.context import spawn
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.secrets import _export_custody, _kek, _source, export_rotator, export_signer
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._rotation import RotatingBroker
from candleviewer.secrets.broker import _IO_TIMEOUT_S, ALLOWED_CALLERS, Purpose, _LoopIo, _m2_only
from candleviewer.secrets.candidate import CANDIDATE_HOLD_S, CandidateKeys, hold_candidate
from candleviewer.secrets.errors import (
    CredentialUnavailable,
    ExportKeyRotationError,
    KekLoadError,
    KekRotationError,
    KekSourceNotPermitted,
    KekUnavailable,
    RotationCode,
)
from candleviewer.secrets.export_rotator import RotationRunning, SigningKeyRotator
from candleviewer.secrets.export_signer import ExportSigner, SigningKeys
from candleviewer.secrets.models import KekCheckResult, RewrapReport, StoredCredential
from candleviewer.secrets.signing import RequestSignature, SigningMessage, scrub_frames
from candleviewer.secrets.store import AuditSink, AuthKeyStore, CredentialStore, KcvStore

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.secrets.store import ExportKeyStore
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
    "launcher with CV_KEK_PREV_HANDLE supplying the previous KEK and finish the re-wrap "
    "(POST /admin/keys/kek-rewrap); if that KEK is lost, revoke those keys at the exchange. "
    "See docs/ops/runbooks/kek-custody.md."
)
#: #2266: a KEK re-wrap run latched order entry before its first row, until the restart.
ROTATION_GATE_REASON = "secrets.kek_rotation"
ROTATION_REMEDIATION = (
    "KEK rotation: a re-wrap run latched order entry read-only before its first row; new orders "
    "stay disabled until the restart that ends the rotation. Cancels and stop-loss amendments "
    "keep signing. See docs/ops/runbooks/kek-custody.md."
)
#: #889: the audit export signing key cannot be used; export alone is refused (ADR-0039).
EXPORT_REMEDIATION = (
    "Audit export signing key unavailable (reason={reason}): export is refused, trading is not. "
    "A stranded key needs CV_KEK_PREV_HANDLE at a restart. See docs/ops/runbooks/kek-custody.md."
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
#: The window of `audit_signing_rotate_rate_per_hour` (#889 S7, 22 `rotateAuditSigningKey`).
_HOUR_S = 3600.0


def _log() -> Any:
    return structlog.get_logger(__name__)


for _r in REASONS:
    m.kek_load_failures_total.labels(reason=_r)


class LatchableGate(Protocol):
    def latch(self, *, reason_code: str, reason_text: str) -> None: ...
    @property
    def latched_reason_code(self) -> str | None: ...


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


def _sealed_borrower(
    resolve: Callable[[], RotatingBroker], caller: str, io: _LoopIo | None = None
) -> CredentialBorrower:
    """Build a signer whose broker resolver lives only in a closure (no attribute to reach)."""
    if caller not in ALLOWED_CALLERS:
        raise ValueError("caller not permitted to borrow credentials")

    async def sign(key_id: UUID, message: SigningMessage, purpose: Purpose) -> RequestSignature:
        return await resolve().borrow_handle(caller, io=io).sign(key_id, message, purpose=purpose)

    return CredentialBorrower(sign)


async def _sink_call(sink: AuditSink | None, action: str, fields: dict[str, str]) -> None:
    """One M2 record, bounded, actor `system/secrets` unless named; failing: `audit_unavailable`."""
    if sink is None:
        raise KekLoadError("audit_unavailable")
    try:
        async with asyncio.timeout(_AUDIT_TIMEOUT_S):
            await sink(action, {"actor_kind": "system", "actor_role": "secrets", **fields})
    except Exception:
        raise KekLoadError("audit_unavailable") from None


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


@final
class LoopSigning:
    """Signing bound to the order lane's loop (#913 L3b, 29 CV-C13): `borrower` reads and records
    through that loop's own store and sink, and refuses any other loop. Closures only (C-3.2).
    #913 L1d: `self_check` proves the binding at the lane's start, and `aclose` also frees the
    pool of the store M2 built for the loop, after the close."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("__check", "__close", "borrower")

    def __init__(
        self,
        borrower: CredentialBorrower,
        close: Callable[[], Awaitable[None]],
        check: Callable[[], Awaitable[None]],
    ) -> None:
        self.borrower, self.__close, self.__check = borrower, close, check

    async def aclose(self) -> None:
        """On its own loop only: no more signing; its writes cancelled and awaited; then the pool
        of the store M2 built for the loop disposed of, once, and counted no more. Each wait is
        bounded by M2's I/O bound; a dispose that fails or outlasts it raises, and the pool stays
        held and counted (`cv_credential_loop_pools_in_use`) until a later `aclose` frees it.
        Idempotent."""
        await self.__close()

    async def self_check(self) -> None:
        """At the lane's start, on its own loop (#913 L1d): what M2's loop check answers a signing
        there, `signing_loop_mismatch` on another loop or once closed, while M2 is degraded too;
        then, with M2 up, one read through the loop's own store of a key no row holds, bounded as
        every read there, so a pool or wiring fault fails the start (`store_unavailable`), never
        an order's signing. A missing row passes. Nothing is recorded, decrypted or counted as a
        borrow."""
        await self.__check()


@final
class KeyDestroyer:
    """Destroys one stored key of one account (#898's delete and revoke; #897's rotation), minted
    once in `admin.wiring`: fenced, recorded with the acting user (SR-E27-09), then revoked, as
    `CredentialBroker.destroy` does; another account's key is refused, nothing touched. It returns
    nothing and raises M2's codes only (C-2.7, C-12.2). Holds a closure only (C-3.2)."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("__destroy",)

    def __init__(self, destroy: Callable[[UUID, UUID, str, str], Awaitable[None]]) -> None:
        self.__destroy = destroy

    async def destroy(
        self, account_id: UUID, key_id: UUID, *, actor_user_id: str, actor_role: str
    ) -> None:
        """Destroy `key_id` if it is `account_id`'s, else `CredentialUnavailable`."""
        await self.__destroy(account_id, key_id, actor_user_id, actor_role)


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
        export_keys: ExportKeyStore | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store, self._kcv, self._audit_sink = store, kcv_store, audit
        self._sources, self._harden = sources, harden
        self._load_timeout = load_timeout_s
        #: The environment's auth keyring rows a re-wrap run counts (#3505).
        self._auth_keys = auth_keys
        #: Its audit export signing keys: boot opens or generates one, a re-wrap run counts them,
        #: and a KEK enrolment with no API key row as evidence trials it (#889, ADR-0039).
        self._export_keys = export_keys
        #: Why the signing key cannot be used while the KEK is up; None when it opens (ADR-0039).
        self._export_reason: str | None = None
        #: #889 S7: the id of the key M2 last checked, at boot or after a rotation; the directory
        #: names, and the listing marks `verified`, no other (decision 4).
        self._export_checked: str | None = None
        self._export_unchecked: str | None = None  # the last unchecked active key logged
        #: #889 S7: the `(owner, Idempotency-Key)` a running rotation serves (single-flight), the
        #: environment's rotation starts in the last hour by `clock`, and their cap, which
        #: `start()` reads (`audit_signing_rotate_rate_per_hour`); no rotation runs before it.
        self._export_rotating: tuple[str, str] | None = None
        self._export_rotations: deque[float] = deque()
        self._rotate_rate, self._clock = 1, clock
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
        await _sink_call(self._audit_sink, action, fields)

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
        self._rotate_rate = settings.audit_signing_rotate_rate_per_hour
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
                loop=asyncio.get_running_loop(),  # #913 L3b: its store and sink serve this loop
            )  # fmt: skip
            try:  # #2266: the previous KEK first, so a wrong one never pins v(n+1)
                if prev is not None:
                    await broker.verify_kcv(prev, self._kcv, must_exist=True)
                await broker.verify_kcv(
                    kek, self._kcv, must_exist=False, export_keys=self._export_keys
                )
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
        if self._export_keys is not None:
            try:
                await self._open_export_key(self._export_keys, kek, prev)
            except BaseException as exc:  # a cancelled boot: unpublished, KEKs zeroed, latched
                self._broker = None
                if isinstance(exc, GeneratorExit):  # the collector's, maybe holding `_guard`
                    broker._zero_keks()  # no lock: nothing signs before this returns
                else:
                    broker.drop_kek()
                m.kek_version.set(0)
                self._latch(ctx, "kek_unavailable")
                raise

    async def _open_export_key(
        self, keys: ExportKeyStore, kek: _kek.LoadedKek, prev: _kek.LoadedKek | None
    ) -> None:
        """#889 (ADR-0039 decision 2), once the KEK is published. A failure degrades `secrets`
        and pages, as a keyring failure does (Amendment 4), then records it at error, as `_degrade`
        does; it latches no order entry: export alone is unavailable. M2 remembers the key the
        check passed for (S7)."""
        try:
            reason, checked = await _export_custody.open_at_boot(keys, kek, prev)
        except Exception as exc:  # a record M2 cannot read: never a reason to stop the boot
            _log().error("secrets.export_key_open_failed", error=type(exc).__name__)
            reason, checked = "export_key_unopenable", None
        self._export_reason, self._export_checked = None, checked
        m.export_key_unavailable_state.set(0)
        if reason is not None:
            await self._export_unavailable(reason)

    async def _export_unavailable(self, reason: str) -> None:
        """Export alone unavailable from now on (ADR-0039 decision 2): `secrets` degraded, the
        page's gauge, a critical log, then the record at error; no order entry is latched."""
        self._export_reason, self._export_checked = reason, None
        m.export_key_unavailable_state.set(1)
        text = EXPORT_REMEDIATION.format(reason=reason)
        _log().critical("secrets.export_key_unavailable", reason=reason, remediation=text)
        try:  # an audit outage must not hide the page above
            await self._audit(_export_custody.UNAVAILABLE, {"env": self._env, "reason": reason})
        except Exception:
            m.credential_outcome_audit_failures_total.inc()

    async def _sign_audit_export(
        self, key_id: object, digest: object, job_id: object, actor_user_id: object
    ) -> bytes:
        """`mint_export_signer`'s call: `export_signer`'s checks in their order (#889, ADR-0039). A
        key found unusable at signing time is latched as at boot (decision 4: refused and paged),
        so neither the signer nor the directory offers it again before a restart, or a rotation
        whose new key passes the check (#889 S7)."""
        checked = export_signer.request(key_id, digest, job_id, actor_user_id)
        keks, keys = self._require()._held_keks(), self._export_keys
        if keys is None or self._export_reason is not None:
            raise CredentialUnavailable("export_key_unavailable")
        try:
            return await export_signer.sign(keys, keks, self._audit, checked, self._export_checked)
        except CredentialUnavailable as exc:
            if str(exc) in export_signer.KEY_FAULTS and self._export_reason is None:
                await self._export_unavailable(str(exc))
            raise

    async def _active_export_key(self) -> export_signer.PublicKey | None:
        """`mint_signing_keys`' call: None while no KEK is held or export is unavailable (22), or
        while the active key is not the one M2 last checked (#889 S7, decision 4): a row swapped
        out of band is named, and marked `verified`, by nothing until a check passes for it. A read
        that overlaps a rotation here logs nothing: the rotation's own check settles it."""
        broker, keys = self._broker, self._export_keys
        if broker is None or keys is None or self._export_reason is not None:
            return None
        checked = self._export_checked  # a rotation here may move it during the read (A2-a)
        named = await export_signer.active_key(keys, broker._held_keks())
        if named is None or named[0] == self._export_checked:
            return named
        settled = checked == self._export_checked and self._export_rotating is None
        if settled and named[0] != self._export_unchecked:  # once a key: the gap (re-check A2)
            self._export_unchecked = named[0]
            _log().error(
                "secrets.export_key_not_checked",
                active_key_id=named[0],
                checked_key_id=self._export_checked,
            )
        return None

    async def _listed_export_keys(self) -> list[dict[str, Any]] | None:
        """`mint_signing_keys`' listing (#889 S7): every key of the environment, newest first, as
        public records with their `verified` mark; None when the store cannot be read (22)."""
        keys, listed = self._export_keys, None
        if keys is not None and self._env:
            try:
                listed = await _export_custody._io(keys.list_keys(self._env))
            except Exception as exc:
                _log().error("secrets.export_key_list_failed", error=type(exc).__name__)
        if listed is None:
            return None
        named = await self._active_export_key()
        return [export_rotator.marked(rec, named and named[0]) for rec in listed]

    async def _marked(self, made: export_rotator.Rotation) -> export_rotator.Rotation:
        named = await self._active_export_key()
        return {k: export_rotator.marked(rec, named and named[0]) for k, rec in made.items()}

    async def _rotate_export_key(
        self, reason: object, owner: object, ref: object, body_sha256: object,
        export_running: Callable[[], bool],
    ) -> tuple[export_rotator.Rotation, bool]:  # fmt: skip
        """`mint_signing_key_rotator`'s call: `export_rotator`'s steps in 22's order (#889 S7). The
        rotation's answer and whether it is a repeat; else `ExportKeyRotationError`."""
        req, keys = export_rotator.request(reason, owner, ref, body_sha256), self._export_keys
        made = await export_rotator.replayed(keys, self._env, req)
        if made is not None:
            return await self._marked(made), True
        if self._export_rotating == (req.owner, req.ref):
            raise ExportKeyRotationError("idempotency_in_flight")
        broker = self._broker
        if broker is None:
            await self._refuse_rotation(export_rotator.NO_KEK, req)
        if (wait := self._rotation_wait()) is not None:
            raise ExportKeyRotationError("rate_limited", wait)  # counted by the caller, unrecorded
        if self._export_rotating is not None or export_running():
            busy = export_rotator.ROTATING if self._export_rotating else export_rotator.EXPORTING
            await self._refuse_rotation(busy, req)
        self._export_rotating = (req.owner, req.ref)  # no await since the checks: single-flight
        try:
            return await self._rotation(broker, keys, req)
        finally:
            self._export_rotating = None

    async def _rotation(
        self, broker: RotatingBroker, keys: ExportKeyStore | None, req: export_rotator.Request
    ) -> tuple[export_rotator.Rotation, bool]:
        """Steps 3 and 4 of `export_rotator`, single-flight: the active key retired for the next."""
        old, failed = None, False
        try:
            old = None if keys is None else await _export_custody._io(keys.active(self._env))
        except Exception as exc:
            _log().error("secrets.export_key_rotation_active_read_failed", error=type(exc).__name__)
            failed = True
        if failed:  # after the handler: nothing chained
            raise ExportKeyRotationError(export_rotator.STORE_DOWN)
        if keys is None or old is None:
            await self._refuse_rotation(export_rotator.NO_KEY, req)
        self._export_rotations.append(self._clock())  # a rotation that starts counts, failed too
        made, code = None, ""
        try:
            made = await export_rotator.rotate(keys, broker._held_keks()[0], req, old)
        except Exception as exc:
            scrub_frames(exc)  # the frames below held the KEK, the DEK and the seed
            code = export_rotator.outcome(exc)
            stopped = {"error": type(exc).__name__, "code": code}
            _log().warning("secrets.export_key_rotation_stopped", **stopped)
        if code == export_rotator.STORE_DOWN:  # its COMMIT may have landed, the answer lost
            with contextlib.suppress(ExportKeyRotationError):  # unread: recorded as failed
                made = await export_rotator.replayed(keys, self._env, req)
            if made is not None:  # it committed: this request's own 200, never a failure
                _log().info("secrets.export_key_rotation_read_back", found=True)
                code = ""
        if code and code != "taken":
            await self._rotation_failed(code, req, old)
        if made is None:  # a retry that raced its first try, or the key retired meanwhile
            again = await export_rotator.replayed(keys, self._env, req)
            if again is None:
                await self._refuse_rotation(export_rotator.ROTATING, req)
            return await self._marked(again), True
        await self._rotated(keys, broker)
        return await self._marked(made), False

    async def _rotated(self, keys: ExportKeyStore, broker: RotatingBroker) -> None:
        """Step 4: export available again, with no restart, once the active key read back passes
        `check_key`: M2 remembers it, the gauge falls to 0 and the health reason clears; else it
        is latched as at boot. A `stop()` before or during the check, its KEK closed, is no
        verdict on the key: the next boot checks it."""
        if self._broker is not broker:
            return
        reason, checked = await export_rotator.checked(keys, broker._held_keks())
        if self._broker is not broker:  # stop() ran during the check
            return
        if reason is not None:
            await self._export_unavailable(reason)
            return
        self._export_reason, self._export_checked = None, checked
        m.export_key_unavailable_state.set(0)

    def _rotation_wait(self) -> int | None:
        """Seconds until the environment may start another rotation, or None: at most
        `audit_signing_rotate_rate_per_hour` start in a rolling hour (22)."""
        now, starts = self._clock(), self._export_rotations
        while starts and now - starts[0] >= _HOUR_S:
            starts.popleft()
        if len(starts) < self._rotate_rate:
            return None
        return max(1, math.ceil(starts[0] + _HOUR_S - now))

    async def _refuse_rotation(self, code: str, req: export_rotator.Request) -> NoReturn:
        """A refusal's record, written before it leaves (C-2.9), else `audit_unavailable`; then
        `kek_unavailable`, or `conflict` with why in the record. Nothing is rotated or latched."""
        answer = export_rotator.NO_KEK if code == export_rotator.NO_KEK else "conflict"
        fields = req.fields(env=self._env, reason=code, requested_reason=req.reason)
        try:
            await self._audit(export_rotator.REFUSED, fields)
        except KekLoadError:
            answer = export_rotator.UNRECORDED
        raise ExportKeyRotationError(answer)  # after the handler: nothing chained

    async def _rotation_failed(
        self, code: str, req: export_rotator.Request, old: Mapping[str, Any]
    ) -> NoReturn:
        """A rotation that did not commit: its record, naming why, the Owner's reason and the key
        it would have retired, then `code`; `audit_unavailable` when that record is lost too."""
        fields = req.fields(env=self._env, reason=code, requested_reason=req.reason)
        try:
            await self._audit(export_rotator.FAILED, fields | {"retired_key_id": old["key_id"]})
        except KekLoadError:
            m.credential_outcome_audit_failures_total.inc()
            code = export_rotator.UNRECORDED
        raise ExportKeyRotationError(code)  # after the handler: nothing chained

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
        (#3505) and the signing keys (#889). The Owner is recorded on every record."""
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
            return await broker.rewrap_all(
                to_version, actor=actor, auth_keys=self._auth_keys, export_keys=self._export_keys
            )
        except CredentialUnavailable as exc:
            audit = str(exc) in _AUDIT_FAILURES
            raise KekRotationError("audit_unavailable" if audit else "store_unavailable") from None
        except KekUnavailable:  # a `stop()` zeroed the KEKs mid-run: a 503, not the refusal
            raise KekRotationError("store_unavailable") from None
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
        """#2266: order entry read-only for the rest of this process. Only a gate no latch holds
        is latched, with the reason `rewrapKek` names, so a repeat notifies nobody; a held latch,
        a stranded boot's or another module's, is the more specific reason and is never buried
        (as `accounts/selfcheck.py` keeps one). Health reads DEGRADED (`kek_rotation`, unless a
        boot latched first); no KEK page (`cv_kek_degraded_state`)."""
        if gate.latched_reason_code is None:
            gate.latch(reason_code=ROTATION_GATE_REASON, reason_text=ROTATION_REMEDIATION)
            _log().warning("secrets.kek_rotation_latched", remediation=ROTATION_REMEDIATION)
        self._reason, self._latched = self._reason or "kek_rotation", True

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
        if self._export_reason is not None:  # export alone is unavailable (#889)
            return HealthReport(
                module="secrets", status=HealthStatus.DEGRADED, detail=self._export_reason
            )
        return HealthReport(module="secrets", status=HealthStatus.OK)


def mint_borrower(service: SecretsService, caller_module: str) -> CredentialBorrower:
    """Wiring-time signing capability bound to `caller_module`. Called once, in
    `admin.wiring.build_secrets_service`; fails closed while degraded."""
    return _sealed_borrower(service._require, caller_module)


#: #913 L1d (Q10): the connections the store M2 builds for another loop, the order lane's, may hold,
#: each opened lazily there: one read per signing, one `last_used_at` write per key a minute.
LOOP_STORE_CONNECTIONS: Final = 4
#: The key id the lane's start-up self-check reads: nil, which `uuid4` never makes, so no row holds
#: it and the read finds none.
_NO_ROW: Final = UUID(int=0)
#: Builds a loop's own credential store over a pool of its own, bounded at the connections M2 asks
#: for, and that pool's dispose: the composition root's, called by M2 alone, on that loop.
LoopStoreFactory = Callable[[int], tuple[CredentialStore, Callable[[], Awaitable[None]]]]


def mint_loop_signing(
    service: SecretsService, caller_module: str, *, loop_store: LoopStoreFactory | None = None
) -> Callable[[AuditSink], LoopSigning]:
    """Wiring-time binder of signing to one more event loop (#913 L3b), minted once, in
    `admin.wiring.secrets_bundle`. It runs on the loop it serves (else `RuntimeError`) with that
    loop's sink, wrapped as the service's own; its borrower resolves the broker per call, as
    `mint_borrower`'s: closed while degraded. #913 L1d: the loop's store is M2's own, built there
    with `loop_store` at `LOOP_STORE_CONNECTIONS` (none wired: `RuntimeError`), never the serving
    loop's (`ValueError`), held by M2 alone and counted in `cv_credential_loop_pools_in_use` until
    `LoopSigning.aclose` frees its pool."""
    if caller_module not in ALLOWED_CALLERS:
        raise ValueError("caller not permitted to borrow credentials")

    def bind(audit: AuditSink) -> LoopSigning:
        loop = asyncio.get_running_loop()  # nothing is built off the loop it serves
        if loop_store is None:
            raise RuntimeError("no loop credential store is wired")
        store, dispose = loop_store(LOOP_STORE_CONNECTIONS)
        if store is service._store:  # a wiring fault, refused before it is counted or read
            raise ValueError("the loop's credential store is its own, never the serving loop's")
        free: Callable[[], Awaitable[None]] | None = dispose
        m.credential_loop_pools.inc()

        async def sink(action: str, fields: dict[str, str]) -> None:
            await _sink_call(audit, action, fields)

        io = _LoopIo(store, sink, loop)

        async def close() -> None:
            nonlocal free
            broker = service._broker  # each wait bounded by its `io_timeout_s`, as its `aclose`
            bound_s = _IO_TIMEOUT_S if broker is None else broker._timeout
            await io.aclose(bound_s)
            if broker is not None:
                broker._leave(io)
            # The close came first, so no signing starts a read now; one already reading is
            # refused at the fence, and its checked-out connection outlives the dispose.
            pool, free = free, None  # claimed before the await: a second close frees nothing
            if pool is None:
                return
            try:
                async with asyncio.timeout(bound_s):
                    await pool()
            except BaseException:
                free = pool  # still held and counted: the next close retries it
                raise
            m.credential_loop_pools.dec()

        async def check() -> None:
            io.bound(caller_module)  # needs no broker: refused off its loop or closed, M2 down too
            broker = service._broker  # degraded: nothing signs until a restart binds the lane anew
            if broker is not None:
                await broker._io(io.store.get(_NO_ROW, broker._env), "store_unavailable")

        borrower = _sealed_borrower(service._require, caller_module, io)
        return LoopSigning(borrower, close, check)

    return bind


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


def mint_key_destroyer(service: SecretsService) -> KeyDestroyer:
    """Wiring-time capability to destroy a stored key (#898; #897 reuses it). Called once, in
    `admin.wiring.secrets_bundle`; it refuses an actor the record cannot name (SR-E27-09) before
    anything else, and fails closed while degraded."""

    async def destroy(account_id: UUID, key_id: UUID, actor_user_id: str, actor_role: str) -> None:
        if not actor_role or not isinstance(actor_user_id, str) or not actor_user_id:
            raise ValueError("a destroy needs the acting user and role (SR-E27-09)")
        UUID(actor_user_id)  # the audit log's actor column is a user id
        actor = ("user", actor_role, actor_user_id)
        await service._require().destroy(key_id, actor=actor, account_id=account_id)

    return KeyDestroyer(destroy)


def mint_export_signer(service: SecretsService) -> ExportSigner:
    """Wiring-time audit export signer (#889, ADR-0039 decision 3). Called once, in
    `admin.wiring.build_secrets_service`; refuses while no KEK is held or export is unavailable."""

    async def sign(key_id: object, digest: object, job_id: object, actor_user_id: object) -> bytes:
        return await service._sign_audit_export(key_id, digest, job_id, actor_user_id)

    return ExportSigner(sign)


def mint_signing_keys(service: SecretsService) -> SigningKeys:
    """Wiring-time directory of the export signing keys (#889, ADR-0039 decisions 3 and 4): the
    active key's public material, and every key's public record with M2's `verified` mark (S7).
    Called once, in `admin.wiring.build_secrets_service`."""

    async def active() -> export_signer.PublicKey | None:
        return await service._active_export_key()

    async def listing() -> list[dict[str, Any]] | None:
        return await service._listed_export_keys()

    return SigningKeys(active, listing)


def mint_signing_key_rotator(service: SecretsService) -> SigningKeyRotator:
    """Wiring-time capability of `rotateAuditSigningKey` (#889 S7, ADR-0039 decision 5), for `admin`
    alone: public key material only. Called once, in `admin.wiring.secrets_bundle`."""

    async def rotate(*call: Any) -> tuple[export_rotator.Rotation, bool]:
        return await service._rotate_export_key(*call)

    return SigningKeyRotator(rotate)


def mint_rotation_running(service: SecretsService) -> RotationRunning:
    """Wiring-time read of the running rotation (#889 S10, ADR-0039 decision 5): `exportAuditLog`'s
    own `409` while a rotation runs for the environment. Called once, in
    `admin.wiring.secrets_bundle`."""

    def running() -> bool:
        return service._export_rotating is not None

    return RotationRunning(running)


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
