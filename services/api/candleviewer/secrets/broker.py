"""Credential broker (E27-T02): store / sign / destroy / KEK re-wrap.

Plaintext keys and unwrapped DEKs exist only in memory inside this module, only between the
decrypt and the end of the request MAC; they never leave M2 (C-2.7, #2339), not even in a
traceback: a failed MAC leaves as a typed `signing_failed` with nothing chained, after the failed
call's frames are cleared, as a failed seal's are. Every action is audited *before* it acts (C-2.9),
with an actor bound at wiring time; every await has a timeout; failures are typed, fail closed and
carry no key material (C-12.6).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, final
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag

from candleviewer.observability.context import spawn
from candleviewer.observability.tracing import span
from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets._permissions import (
    project_snapshot,
    reject_withdraw,
    require_allow_listed,
)
from candleviewer.secrets.errors import (
    CredentialUnavailable,
    KekLoadError,
    KekUnavailable,
    SecretsError,
    SnapshotInvalid,
    WithdrawPermissionRejected,
)
from candleviewer.secrets.models import CredentialRow, StoredCredential
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.signing import (
    RequestSignature,
    SigningMessage,
    check_message,
    message_sha256,
    request_signature,
    scrub_frames,
)
from candleviewer.secrets.store import AuditSink, CredentialStore

Clock = Callable[[], float]
Purpose = Literal["sign_rest", "sign_ws_auth", "key_verify"]

#: Callers a borrow capability may be bound to (C-3.2: M4, the exchange adapter, only).
#: Also the bounded value set of the `stage` metric label.
ALLOWED_CALLERS = frozenset({"exchange_adapter"})
_PURPOSES = frozenset({"sign_rest", "sign_ws_auth", "key_verify"})
#: `api_keys.status` values (0017 `key_status`) that may be used to sign trading requests.
_SIGNABLE = frozenset({"active", "rotating"})
_TOUCH_INTERVAL_S = 60.0
_IO_TIMEOUT_S = 2.0
_SYSTEM = ("system", "secrets", None)
#: Closes a write-ahead `security.credential_borrowed` record when signing fails after it.
_SIGN_FAILED = "security.credential_sign_failed"


def _failure_reason(exc: BaseException) -> str:
    """Bounded `reason` of a failure-outcome record: M2's own reason code (codes only, never
    key material, `errors.py`), else the kind of failure."""
    if isinstance(exc, SecretsError):
        code = str(exc)
        return code if code.isascii() and code.isidentifier() else "error"
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    return "error" if isinstance(exc, Exception) else "interrupted"


def _m2_only(cls: type) -> None:
    """R7 runtime backstop: classes holding M2 capabilities are subclassable only inside M2."""
    if not cls.__module__.startswith("candleviewer.secrets."):
        raise TypeError(f"{cls.__qualname__}: M2 classes may not be subclassed outside secrets/")


class _DekCache:
    def __init__(self, ttl_s: float, clock: Clock) -> None:
        self._ttl, self._clock = ttl_s, clock
        self._items: dict[UUID, tuple[float, bytearray]] = {}

    def sweep(self) -> None:
        """Zero every expired entry (called on every cache access, so an idle key's DEK never
        outlives the TTL by more than one access to any key; a stop() flushes everything)."""
        now = self._clock()
        for k in [k for k, (exp, _) in self._items.items() if now >= exp]:
            self.flush(k)

    def get(self, key_id: UUID) -> bytearray | None:
        self.sweep()
        hit = self._items.get(key_id)
        if hit is None:
            return None
        if self._clock() >= hit[0]:
            self.flush(key_id)
            return None
        return hit[1]

    def put(self, key_id: UUID, dek: bytearray) -> None:
        self.sweep()
        if self._ttl > 0:
            self.flush(key_id)
            self._items[key_id] = (self._clock() + self._ttl, dek)

    def holds(self, key_id: UUID, dek: bytearray) -> bool:
        item = self._items.get(key_id)
        return item is not None and item[1] is dek

    def flush(self, key_id: UUID | None = None) -> None:
        for k in list(self._items) if key_id is None else [key_id]:
            item = self._items.pop(k, None)
            if item is not None:
                env.zero(item[1])

    def __len__(self) -> int:
        return len(self._items)


class CredentialBroker:
    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    def __init__(
        self,
        store: CredentialStore,
        audit: AuditSink,
        kek: LoadedKek | None,
        *,
        prev_kek: LoadedKek | None = None,
        dek_cache_ttl_s: float = 300.0,
        io_timeout_s: float = _IO_TIMEOUT_S,
        clock: Clock = time.monotonic,
        env_name: str = "demo",
    ) -> None:
        if any(k is not None and k.env_name != env_name for k in (kek, prev_kek)):
            # #2338: a KEK opens only its own environment's wraps; never re-bind one here.
            for k in (kek, prev_kek):
                if k is not None:
                    k.close()  # zeroed before the refusal leaves, like drop_kek()
            raise ValueError("KEK loaded for another environment")
        self._store, self._audit_sink = store, audit
        self._kek, self._prev = kek, prev_kek
        self._cache = _DekCache(dek_cache_ttl_s, clock)
        self._clock, self._timeout = clock, io_timeout_s
        self._last_touch: dict[UUID, float] = {}
        #: In-flight `last_used_at` writes, at most one per key (#2776), so their number is
        #: bounded by the number of keys (C-2.18). Owned here: `destroy` and `aclose` cancel them.
        self._touches: dict[UUID, asyncio.Task[None]] = {}
        self._touch_closed = False
        self._destroyed: set[UUID] = set()
        self._env = env_name

    async def _io[T](self, aw: Awaitable[T], code: str) -> T:
        """Bounded and typed: a timeout or any non-M2 error leaves M2 as
        `CredentialUnavailable(code)`; cancellation and M2 errors propagate unchanged."""
        try:
            async with asyncio.timeout(self._timeout):
                return await aw
        except (SecretsError, asyncio.CancelledError):
            raise
        except Exception:
            raise CredentialUnavailable(code) from None

    async def _audit(self, action: str, fields: dict[str, str]) -> None:
        try:
            await self._io(self._audit_sink(action, fields), "audit_timeout")
        except KekLoadError:  # the service sink's own refusal: a typed borrow-side error
            raise CredentialUnavailable("audit_unavailable") from None

    def _require_kek(self) -> LoadedKek:
        if self._kek is None:
            raise KekUnavailable("kek_unavailable")
        return self._kek

    def drop_kek(self) -> None:
        """Zero everything, fail closed from now on (stop / runtime loss)."""
        self._cache.flush()
        for k in (self._kek, self._prev):
            if k is not None:
                k.close()
        self._kek = self._prev = None

    def borrow_handle(self, caller_module: str) -> BorrowHandle:
        """Wiring-time binding of a caller identity (C-3.2, C-2.9)."""
        return BorrowHandle(self, caller_module)

    async def store(
        self,
        env_name: str,
        account_id: UUID,
        label: str,
        api_key: Secret[str],
        api_secret: Secret[str],
        permission_snapshot: Mapping[str, Any],
        *,
        actor: tuple[str, str, str | None] = _SYSTEM,
    ) -> StoredCredential:
        args = (env_name, account_id, label, api_key, api_secret, permission_snapshot, actor)
        return await self._seal_new(uuid4(), *args)

    async def _seal_new(
        self,
        key_id: UUID,
        env_name: str,
        account_id: UUID,
        label: str,
        api_key: Secret[str],
        api_secret: Secret[str],
        permission_snapshot: Mapping[str, Any],
        actor: tuple[str, str, str | None],
    ) -> StoredCredential:
        """Seal and insert a `pending` row under `key_id`, which M2 mints (#2336): `store()` per
        call, a candidate's hold when it starts (`candidate.py`, so the hold's signing records and
        the row share the id). No caller outside M2 chooses a credential id."""
        if env_name != self._env:
            raise CredentialUnavailable("environment_mismatch")
        snapshot = project_snapshot(permission_snapshot)
        kek = self._require_kek()
        # The pasted key id, like the secret, is never a local: no rendered frame shows it (C-12.6).
        last4 = api_key.reveal()[-4:]
        if len(api_key.reveal()) < 4 or not last4.isascii() or not last4.isalnum():
            raise CredentialUnavailable("credential_shape_invalid")
        dek = env.new_dek()
        try:
            dek_ref = kek.wrap_dek(dek, credential_id=key_id)
            aad_k = env.cred_aad(env_name, account_id, key_id, "key_id")
            aad_s = env.cred_aad(env_name, account_id, key_id, "secret")
            key_enc = env.seal(dek, api_key.reveal().encode(), aad_k)
            secret_enc = env.seal(dek, api_secret.reveal().encode(), aad_s)
        except BaseException as exc:
            scrub_frames(exc)  # the frames below hold the KEK, the DEK and the pasted pair (C-12.6)
            raise
        finally:
            env.zero(dek)
        row = CredentialRow(
            id=key_id,
            exchange_account_id=account_id,
            env=env_name,
            label=label,
            key_id_enc=key_enc,
            key_id_last4=last4,
            secret_enc=secret_enc,
            enc_nonce=secret_enc[: env.NONCE_LEN],
            dek_ref=dek_ref,
            kek_version=kek.version,
            permission_snapshot=snapshot,
        )
        await self._audit("security.credential_stored", self._fields(row, actor=actor))
        try:
            await self._io(self._store.insert(row.to_record()), "store_unavailable")
        except BaseException as exc:
            await self._outcome("security.credential_store_failed", row, actor)
            if isinstance(exc, Exception) and not isinstance(exc, CredentialUnavailable):
                raise CredentialUnavailable("store_failed") from None
            raise
        return StoredCredential(key_id, account_id, label, last4, kek.version)

    async def _load(self, key_id: UUID) -> CredentialRow | None:
        rec = await self._io(self._store.get(key_id, self._env), "store_unavailable")
        if rec is None:
            return None
        # A fund flag the store did not return is `None`, never false: refused (SR-E27-14).
        return CredentialRow(**{"can_withdraw": None, "can_transfer": None, **rec})

    @staticmethod
    def _fields(
        row: CredentialRow, *, actor: tuple[str, str, str | None] = _SYSTEM, **extra: str
    ) -> dict[str, str]:
        kind, role, user = actor
        out = {
            "key_id": str(row.id),
            "exchange_account_id": str(row.exchange_account_id),
            "env": row.env,
            "kek_version": str(row.kek_version),
            "actor_kind": kind,
            "actor_role": role,
            **extra,
        }
        if user is not None:
            out["actor_user_id"] = user
        return out

    def _dek_for(self, row: CredentialRow, kek: LoadedKek) -> bytearray:
        cached = self._cache.get(row.id)
        if cached is not None:
            m.dek_cache_hits_total.inc()
            return cached
        if row.kek_version == kek.version:
            wrap = kek
        elif self._prev is not None and row.kek_version == self._prev.version:
            wrap = self._prev  # mid-rotation: row not yet re-wrapped
        else:
            raise CredentialUnavailable("credential_unavailable")
        dek = wrap.unwrap_dek(row.dek_ref, credential_id=row.id)
        if len(dek) != env.KEY_LEN:
            env.zero(dek)
            raise ValueError("dek length")
        self._cache.put(row.id, dek)
        return dek

    def _touch(self, key_id: UUID) -> None:
        """Best-effort `last_used_at` (21 §3.2.2) that never delays a signing (#2776): the write
        runs in a task this broker owns and is never awaited here. At most one attempt per key per
        `_TOUCH_INTERVAL_S`: the window is stamped *before* the write, so a failed or stalled
        attempt is debounced exactly like a successful one. At most one write per key is in
        flight; a signing that finds one starts none. After `aclose` no write starts."""
        if self._touch_closed or key_id in self._touches:
            return
        now = self._clock()
        prev = self._last_touch.get(key_id)
        if prev is not None and now - prev < _TOUCH_INTERVAL_S:
            return
        self._last_touch[key_id] = now
        # The write is handed over as a bound method: this debouncer stays the only code that
        # names it (#2580), and no store coroutine exists unless the task really starts.
        write = self._write_touch(self._store.touch_last_used, key_id, self._timeout)
        task = spawn(write, name="secrets-credential-touch")
        touches = self._touches
        touches[key_id] = task

        def forget(done: asyncio.Task[None]) -> None:
            if touches.get(key_id) is done:  # by identity: never drops another write's entry
                del touches[key_id]

        task.add_done_callback(forget)

    @staticmethod
    async def _write_touch(
        write: Callable[[UUID], Awaitable[None]], key_id: UUID, timeout_s: float
    ) -> None:
        """Body of a `_touch` task: one write, bounded by `io_timeout_s`. A failure or timeout is
        counted, never raised (nothing awaits it); cancellation (`destroy`, `aclose`) is not a
        failure and propagates. Static, so the task holds the store's write, the key id and the
        bound, and never the broker: no KEK, no DEK, no plaintext."""
        try:
            async with asyncio.timeout(timeout_s):
                await write(key_id)
        except Exception:
            m.credential_touch_failures_total.inc()

    async def aclose(self) -> None:
        """Shutdown of the broker's own tasks; its owner calls this on stop (`SecretsService.stop`,
        after `drop_kek`). No `last_used_at` write starts from now on. Every in-flight one is
        cancelled and awaited, so none is left pending. Each wait is bounded by `io_timeout_s`;
        a write still running then (its cleanup stalled again, e.g. a rollback and then a close
        on a wedged connection) is cancelled again, until every write has ended.
        Idempotent; signing is not affected."""
        self._touch_closed = True
        pending = set(self._touches.values())
        while pending:
            for write in pending:
                write.cancel()
            _, pending = await asyncio.wait(pending, timeout=self._timeout)

    def _check_row(
        self, row: CredentialRow | None, key_id: UUID, purpose: str, *, fence: bool = False
    ) -> CredentialRow:
        """`fence`: the post-audit check of the row already checked, so C-2.8 runs once."""
        if row is None or row.revoked or key_id in self._destroyed or row.env != self._env:
            self._cache.flush(key_id)
            raise CredentialUnavailable("credential_unavailable")
        if not fence:  # C-2.8 first (SR-E27-14), before the status check
            self._recheck_fund_rights(row)
        allowed = _SIGNABLE | ({"pending"} if purpose == "key_verify" else set())
        if row.status not in allowed or row.enc_alg != "AES-256-GCM":
            raise CredentialUnavailable("credential_unavailable")
        return row

    def _recheck_fund_rights(self, row: CredentialRow) -> None:
        """SR-E27-14: a stored row must still pass C-2.8 before anything decrypts it. Its
        withdraw and transfer flags are false (`ak_no_withdraw`, `ak_no_transfer`), and the rights
        in its snapshot pass the allow-list and the deny-list `store()` applied (#2270). The
        database CHECK keeps only the deny-list, so a row edited since it was stored (KV-T03) is
        refused here, fail closed, before the audit and the decrypt, and its DEK is flushed."""
        snapshot: object = row.permission_snapshot
        rights = snapshot.get("permissions") if isinstance(snapshot, dict) else None
        try:
            if row.can_withdraw is not False or row.can_transfer is not False:
                raise WithdrawPermissionRejected("key_withdraw_permission")
            if not isinstance(rights, dict):
                raise SnapshotInvalid("snapshot_invalid")
            require_allow_listed(rights)
            reject_withdraw(rights)
        except WithdrawPermissionRejected:
            self._cache.flush(row.id)
            raise

    async def _borrow[T](
        self,
        key_id: UUID,
        fn: Callable[[Secret[str], Secret[str]], Awaitable[T]],
        caller_module: str,
        purpose: str,
        *,
        digest: str | None = None,
    ) -> T:
        """The single audited decrypt path. Its only production caller is `_sign`, which
        uses the secret for the request MAC inside M2 and returns no plaintext secret (C-2.7,
        #2339). (Two internal
        decrypts exist and never leave M2: `_dek_for` returns an unwrapped DEK to this method,
        and `_rotation._rewrap_one` opens `secret_enc` to verify a re-wrap, zeroes it, and is
        covered by the run-level rotation audit.) Caller check, env-namespaced
        load, status/fence check, write-ahead audit and the fence re-check all run here, in
        the same frame, immediately before `open_` (C-2.9). There is no separate decrypt
        method to call without them. In-process Python cannot make that impossible — a module
        can still reach the KEK by introspection — so the CI guard
        (`test_capability_boundary.py`) is the enforcing control; process isolation of
        signing is the real fix (#835 residual, follow-up issue). The write-ahead record
        carries `digest` as `message_sha256`; any failure after it (fence, decrypt, MAC,
        cancellation) appends `security.credential_sign_failed` with a bounded `reason`."""
        if caller_module not in ALLOWED_CALLERS or purpose not in _PURPOSES:
            raise CredentialUnavailable("caller_not_permitted")
        actor = ("system", caller_module, None)
        extra = {"caller_module": caller_module, "purpose": purpose}
        if digest is not None:
            extra["message_sha256"] = digest
        result = "error"
        audited: dict[str, str] | None = None
        try:
            kek = self._require_kek()
            row = self._check_row(await self._load(key_id), key_id, purpose)
            fields = self._fields(row, actor=actor, **extra)
            await self._audit("security.credential_borrowed", fields)
            audited = fields
            row = self._check_row(row, key_id, purpose, fence=True)  # destroyed during the audit?
            self._touch(key_id)  # started, never awaited: metadata never delays a signing
            attrs = {k: fields[k] for k in ("key_id", "env", "kek_version")}
            started = time.perf_counter()
            key = secret = dek = None
            k_s: Secret[str] | None = None
            s_s: Secret[str] | None = None
            try:
                with span("secrets.credential_borrow", {**attrs, "purpose": purpose}):
                    try:
                        if row.secret_enc[: env.NONCE_LEN] != row.enc_nonce:
                            raise ValueError("enc_nonce mismatch")
                        dek = self._dek_for(row, kek)
                        acct, rid = row.exchange_account_id, row.id
                        # C-2.11: AAD from the process environment (never a DB-read field).
                        bound = self._env
                        aad_k = env.cred_aad(bound, acct, rid, "key_id")
                        key = env.open_(dek, row.key_id_enc, aad_k)
                        aad_s = env.cred_aad(bound, acct, rid, "secret")
                        secret = env.open_(dek, row.secret_enc, aad_s)
                    except (InvalidTag, ValueError):
                        self._cache.flush(row.id)
                        raise CredentialUnavailable("credential_unavailable") from None
                    m.credential_borrow_seconds.observe(time.perf_counter() - started)
                    k_s, s_s = Secret(key.decode()), Secret(secret.decode())
                    out = await fn(k_s, s_s)
            finally:
                for buf in (key, secret):
                    if buf is not None:
                        env.zero(buf)
                if dek is not None and not self._cache.holds(row.id, dek):
                    env.zero(dek)
                for sec in (k_s, s_s):
                    if sec is not None:
                        sec.invalidate()
                # Drop plaintext references so a rendered traceback's frame locals
                # (structlog dict_tracebacks / capture_locals) can never see them.
                key = secret = dek = None
                k_s = s_s = None
            result = "ok"
            return out
        except BaseException as exc:
            if audited is not None:  # close the write-ahead record (C-2.9)
                await self._sign_failed(audited, exc)
            raise
        finally:
            m.credential_borrow_total.labels(stage=caller_module, result=result).inc()

    async def _sign(
        self, key_id: UUID, message: SigningMessage, caller_module: str, purpose: str
    ) -> RequestSignature:
        """M2-side request signing (C-2.7, #2339): the secret is used for the MAC here and
        never leaves M2. The result holds the hex MAC and the key id the caller's request
        header needs. A message `check_message` refuses (shape or bounds: size, parts, slots) is
        refused before the borrow (no decrypt, no audit).
        """
        parts = check_message(message)

        async def mac(k: Secret[str], s: Secret[str]) -> RequestSignature:
            return request_signature(k, s, parts)  # `k`/`s`: wrappers `_borrow` invalidates

        return await self._borrow(key_id, mac, caller_module, purpose, digest=message_sha256(parts))

    async def destroy(self, key_id: UUID, *, actor: tuple[str, str, str | None] = _SYSTEM) -> None:
        """Fence first (in-flight borrows refuse at their post-audit re-check, and the key's
        pending `last_used_at` write is cancelled), then audit, flush and revoke. A failure keeps
        the key fenced for this process (fail closed) and appends
        `security.credential_destroy_failed`; the original error is always re-raised."""
        row = await self._load(key_id)
        if row is None:
            self._cache.flush(key_id)
            raise CredentialUnavailable("credential_unavailable")
        self._destroyed.add(key_id)
        self._cache.flush(key_id)
        write = self._touches.get(key_id)
        if write is not None:  # #2776: drop its pending write (one already committed stays)
            write.cancel()
        try:
            await self._audit("security.credential_destroyed", self._fields(row, actor=actor))
            await self._io(self._store.mark_revoked(key_id), "store_unavailable")
        except BaseException:
            await self._outcome("security.credential_destroy_failed", row, actor)
            raise
        finally:
            self._cache.flush(key_id)

    async def _outcome(
        self, action: str, row: CredentialRow, actor: tuple[str, str, str | None], **extra: str
    ) -> None:
        """Best-effort failure-outcome record; never replaces the original exception."""
        try:
            await self._audit(action, self._fields(row, actor=actor, **extra))
        except Exception:
            m.credential_outcome_audit_failures_total.inc()

    async def _sign_failed(self, borrowed: dict[str, str], exc: BaseException) -> None:
        """Close a write-ahead `security.credential_borrowed` record with the bounded `reason`
        of `exc`, best effort like `_outcome`. Every signing path closes its record here."""
        try:
            await self._audit(_SIGN_FAILED, {**borrowed, "reason": _failure_reason(exc)})
        except Exception:
            m.credential_outcome_audit_failures_total.inc()

    def flush_cache(self, key_id: UUID | None = None) -> None:
        """Flush on revoke/rotate (E27-S03/S04) and on KEK rotation."""
        self._cache.flush(key_id)


@final
class BorrowHandle:
    """A signing capability bound to one caller module at wiring time. It yields a MAC and the
    key id, never plaintext secrets (C-2.7, #2339)."""

    def __init_subclass__(cls, **kw: Any) -> None:
        _m2_only(cls)
        super().__init_subclass__(**kw)

    __slots__ = ("_broker", "_caller")

    def __init__(self, broker: CredentialBroker, caller_module: str) -> None:
        if caller_module not in ALLOWED_CALLERS:
            raise ValueError("caller not permitted to borrow credentials")
        self._broker, self._caller = broker, caller_module

    async def sign(
        self, key_id: UUID, message: SigningMessage, *, purpose: Purpose
    ) -> RequestSignature:
        """M2 signs `message` with the credential's API secret (see `CredentialBroker._sign`)."""
        return await self._broker._sign(key_id, message, self._caller, purpose)
