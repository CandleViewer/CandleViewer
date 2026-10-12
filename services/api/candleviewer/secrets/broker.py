"""Credential broker (E27-T02): store / scoped borrow / destroy / KEK re-wrap.

Plaintext keys and unwrapped DEKs exist only in memory inside this module. There is no
`get_secret()`: callers get plaintext only inside `with_credentials(key_id, fn)`, and every
borrow, store and destroy writes an audit record *before* acting (C-2.9). Any failure is
fail-closed and surfaces a typed error whose message carries no key material (C-12.6).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag

from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets.errors import (
    CredentialUnavailable,
    KekUnavailable,
    WithdrawPermissionRejected,
)
from candleviewer.secrets.models import CredentialRow, RewrapReport, StoredCredential
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.store import AuditSink, CredentialStore

Clock = Callable[[], float]

#: Bounded metric label values for `caller_module` (anything else is reported as `other`).
_TOUCH_INTERVAL_S = 60.0
_KNOWN_CALLERS = frozenset({"exchange_adapter", "admin"})


def reject_withdraw(permissions: Mapping[str, object]) -> None:
    """C-2.8: any permission key containing `withdraw` (any case/whitespace) with a
    non-empty value rejects the key. Stricter than an exact `Withdraw` match (#2153 review)."""
    for name, value in permissions.items():
        if "withdraw" in name.strip().lower() and value not in (None, "", [], (), {}, False):
            raise WithdrawPermissionRejected("key_withdraw_permission")


class _DekCache:
    def __init__(self, ttl_s: float, clock: Clock) -> None:
        self._ttl, self._clock = ttl_s, clock
        self._items: dict[UUID, tuple[float, bytearray]] = {}

    def get(self, key_id: UUID) -> bytearray | None:
        hit = self._items.get(key_id)
        if hit is None:
            return None
        if self._clock() >= hit[0]:
            self.flush(key_id)
            return None
        return hit[1]

    def put(self, key_id: UUID, dek: bytearray) -> None:
        if self._ttl > 0:
            self.flush(key_id)
            self._items[key_id] = (self._clock() + self._ttl, dek)

    def flush(self, key_id: UUID | None = None) -> None:
        ids = list(self._items) if key_id is None else [key_id]
        for k in ids:
            item = self._items.pop(k, None)
            if item is not None:
                env.zero(item[1])

    def holds(self, key_id: UUID, dek: bytearray) -> bool:
        item = self._items.get(key_id)
        return item is not None and item[1] is dek

    def __len__(self) -> int:
        return len(self._items)


class CredentialBroker:
    def __init__(
        self,
        store: CredentialStore,
        audit: AuditSink,
        kek: LoadedKek | None,
        *,
        prev_kek: LoadedKek | None = None,
        dek_cache_ttl_s: float = 300.0,
        clock: Clock = time.monotonic,
    ) -> None:
        self._store, self._audit = store, audit
        self._kek, self._prev = kek, prev_kek
        self._cache = _DekCache(dek_cache_ttl_s, clock)
        self._clock = clock
        self._last_touch: dict[UUID, float] = {}

    async def _touch(self, key_id: UUID) -> None:
        """`last_used_at`, debounced to one write per key per 60 s (21 §3.2.2, as E27-T01)."""
        now = self._clock()
        prev = self._last_touch.get(key_id)
        if prev is None or now - prev >= _TOUCH_INTERVAL_S:
            await self._store.touch_last_used(key_id)
            self._last_touch[key_id] = now

    def _require_kek(self) -> LoadedKek:
        if self._kek is None:
            raise KekUnavailable("kek_unavailable")
        return self._kek

    def drop_kek(self) -> None:
        """Called when the KEK is lost at runtime: zero everything, fail closed from now on."""
        self._cache.flush()
        for k in (self._kek, self._prev):
            if k is not None:
                k.close()
        self._kek = self._prev = None

    async def store(
        self,
        account_id: UUID,
        label: str,
        api_key: Secret[str],
        api_secret: Secret[str],
        permission_snapshot: Mapping[str, Any],
    ) -> StoredCredential:
        perms = permission_snapshot.get("permissions")
        if not isinstance(perms, Mapping):
            raise WithdrawPermissionRejected("key_withdraw_permission")
        reject_withdraw(perms)
        kek = self._require_kek()
        key_plain = api_key.reveal()
        last4 = key_plain[-4:]
        if len(key_plain) < 4 or not last4.isascii() or not last4.isalnum():
            raise CredentialUnavailable("credential_shape_invalid")
        key_id = uuid4()
        dek = env.new_dek()
        try:
            dek_ref = kek.wrap_dek(dek, credential_id=key_id)
            k_nonce, k_sealed = env.seal(
                dek, key_plain.encode(), env.cred_aad(account_id, key_id, "key_id")
            )
            s_nonce, s_sealed = env.seal(
                dek, api_secret.reveal().encode(), env.cred_aad(account_id, key_id, "secret")
            )
        finally:
            env.zero(dek)
        row = CredentialRow(
            id=key_id,
            exchange_account_id=account_id,
            label=label,
            key_id_enc=k_nonce + k_sealed,
            key_id_last4=last4,
            secret_enc=s_sealed,
            enc_nonce=s_nonce,
            dek_ref=dek_ref,
            kek_version=kek.version,
            permission_snapshot=dict(permission_snapshot),
        )
        await self._audit("security.credential_stored", self._fields(row))
        await self._store.insert(row.to_record())
        return StoredCredential(key_id, account_id, label, last4, kek.version)

    async def _load(self, key_id: UUID) -> CredentialRow | None:
        rec = await self._store.get(key_id)
        return CredentialRow(**rec) if rec is not None else None

    @staticmethod
    def _fields(row: CredentialRow, **extra: str) -> dict[str, str]:
        return {
            "key_id": str(row.id),
            "exchange_account_id": str(row.exchange_account_id),
            "kek_version": str(row.kek_version),
            **extra,
        }

    def _dek_for(self, row: CredentialRow, kek: LoadedKek) -> bytearray:
        cached = self._cache.get(row.id)
        if cached is not None:
            m.dek_cache_hits_total.inc()
            return cached
        if row.kek_version != kek.version:
            raise CredentialUnavailable("credential_unavailable")
        dek = kek.unwrap_dek(row.dek_ref, credential_id=row.id)
        self._cache.put(row.id, dek)
        return dek

    async def with_credentials[T](
        self,
        key_id: UUID,
        fn: Callable[[Secret[str], Secret[str]], Awaitable[T]],
        *,
        caller_module: str,
        purpose: str,
    ) -> T:
        """Scoped borrow: plaintext lives only for the duration of `fn`."""
        result = "error"
        try:
            kek = self._require_kek()
            row = await self._load(key_id)
            if row is None or row.revoked:
                raise CredentialUnavailable("credential_unavailable")
            await self._audit(
                "security.credential_borrowed",
                self._fields(row, caller_module=caller_module, purpose=purpose),
            )
            started = time.perf_counter()
            try:
                dek = self._dek_for(row, kek)
                key = env.open_(
                    dek,
                    row.key_id_enc[: env.NONCE_LEN],
                    row.key_id_enc[env.NONCE_LEN :],
                    env.cred_aad(row.exchange_account_id, row.id, "key_id"),
                )
                secret = env.open_(
                    dek,
                    row.enc_nonce,
                    row.secret_enc,
                    env.cred_aad(row.exchange_account_id, row.id, "secret"),
                )
            except (InvalidTag, ValueError):
                self._cache.flush(key_id)
                raise CredentialUnavailable("credential_unavailable") from None
            if not self._cache.holds(key_id, dek):
                env.zero(dek)
            m.credential_borrow_seconds.observe(time.perf_counter() - started)
            await self._touch(key_id)
            out = await fn(Secret(key.decode()), Secret(secret.decode()))
            result = "ok"
            return out
        finally:
            m.credential_borrow_total.labels(
                stage=caller_module if caller_module in _KNOWN_CALLERS else "other", result=result
            ).inc()

    async def destroy(self, key_id: UUID) -> None:
        self._cache.flush(key_id)
        row = await self._load(key_id)
        fields = self._fields(row) if row else {"key_id": str(key_id)}
        await self._audit("security.credential_destroyed", fields)
        await self._store.mark_revoked(key_id)

    def flush_cache(self, key_id: UUID | None = None) -> None:
        """Flush on revoke/rotate (E27-S03/S04) and on KEK rotation."""
        self._cache.flush(key_id)

    async def rewrap_all(self, new_kek_version: int, *, batch: int = 50) -> RewrapReport:
        """Re-wrap every DEK at `new_kek_version - 1` under the current KEK.

        Requires the current KEK at `new_kek_version` and the previous one loaded. Ciphertext
        and `enc_nonce` are untouched. Per-row compare-and-set makes it idempotent and
        resumable: a killed run leaves every row either fully old or fully new.
        """
        kek, prev = self._require_kek(), self._prev
        if prev is None or kek.version != new_kek_version or prev.version != kek.version - 1:
            raise KekUnavailable("kek_unavailable")
        self._cache.flush()
        remaining = await self._store.count_at_kek_version(prev.version)
        base = {"from": str(prev.version), "to": str(kek.version), "rows": str(remaining)}
        await self._audit("security.kek_rotation_started", base)
        done = 0
        while ids := await self._store.ids_at_kek_version(prev.version, batch):
            for key_id in ids:
                row = await self._load(key_id)
                if row is None or row.kek_version != prev.version:
                    continue
                try:
                    dek = prev.unwrap_dek(row.dek_ref, credential_id=row.id)
                except (InvalidTag, ValueError):
                    raise CredentialUnavailable("credential_unavailable") from None
                try:
                    new_ref = kek.wrap_dek(dek, credential_id=row.id)
                finally:
                    env.zero(dek)
                if await self._store.rewrap(
                    row.id, from_version=prev.version, dek_ref=new_ref, kek_version=kek.version
                ):
                    done += 1
                    m.credential_rewrap_rows_total.inc()
        left = await self._store.count_at_kek_version(prev.version)
        await self._audit("security.kek_rotated", {**base, "rows": str(done)})
        return RewrapReport(prev.version, kek.version, done, left)
