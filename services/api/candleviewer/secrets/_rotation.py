"""KEK lifecycle on top of the broker (E27-T02): KCV verification without trust-on-first-use
and the resumable, verified DEK re-wrap (e27-kek.md §5). Private to M2."""

from __future__ import annotations

from cryptography.exceptions import InvalidTag

from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._kek import LoadedKek, kcv_matches
from candleviewer.secrets.broker import _SYSTEM, CredentialBroker
from candleviewer.secrets.errors import KekLoadError, KekUnavailable
from candleviewer.secrets.models import CredentialRow, RewrapReport
from candleviewer.secrets.store import KcvStore


class RotatingBroker(CredentialBroker):
    """The broker the service runs: borrow/store/destroy plus KCV and KEK re-wrap."""

    async def verify_kcv(self, kek: LoadedKek, kcvs: KcvStore, *, must_exist: bool) -> bool:
        """No trust-on-first-use. Returns True iff this call enrolled a new KCV.

        An unknown KCV is recorded only if no live row exists at that version, or after a
        trial unwrap of one such row succeeds; `must_exist` (previous KEK) refuses unknown.
        """
        expected = await self._io(kcvs.kcv_for(kek.version), "kcv_store_unavailable")
        enrolled = False
        if expected is None:
            if must_exist:
                raise KekLoadError("kek_mismatch")
            ids = await self._io(self._store.ids_at_kek_version(kek.version, 1, self._env), "store")
            if ids:
                row = await self._load(ids[0])
                try:
                    if row is None:
                        raise ValueError("row vanished")
                    env.zero(kek.unwrap_dek(row.dek_ref, credential_id=row.id))
                except (InvalidTag, ValueError):
                    raise KekLoadError("kek_mismatch") from None
            stored = kcvs.record_kcv(kek.version, kek.kcv())
            expected = await self._io(stored, "kcv_store_unavailable")
            enrolled = True
        if not kcv_matches(kek, expected):
            raise KekLoadError("kek_mismatch")
        return enrolled

    async def rewrap_all(
        self,
        new_kek_version: int,
        *,
        actor: tuple[str, str, str | None] = _SYSTEM,
        batch: int = 50,
    ) -> RewrapReport:
        """Re-wrap every DEK at `new_kek_version - 1` under the current KEK (e27-kek.md §5).

        Ciphertext/nonces untouched; each new wrap is verified by opening `secret_enc` before
        the compare-and-set. Keyset paging terminates; failures are audited as they occur;
        `kek_rotated` only when nothing is left, otherwise `kek_rotation_incomplete`.
        """
        kek, prev = self._require_kek(), self._prev
        if prev is None or kek.version != new_kek_version or prev.version != kek.version - 1:
            raise KekUnavailable("kek_unavailable")
        if kcv_matches(kek, prev.kcv()):
            raise KekLoadError("kek_reused")  # a no-op "rotation" must not be recorded
        self._cache.flush()
        total = await self._io(self._store.count_at_kek_version(prev.version, self._env), "store")
        kind, role, user = actor
        base = {
            "from": str(prev.version),
            "to": str(kek.version),
            "from_kcv": prev.kcv().hex(),
            "to_kcv": kek.kcv().hex(),
            "actor_kind": kind,
            "actor_role": role,
            **({"actor_user_id": user} if user else {}),
        }
        await self._audit("security.kek_rotation_started", {**base, "rows": str(total)})
        done, failed, after = 0, [], None
        try:
            while ids := await self._io(
                self._store.ids_at_kek_version(prev.version, batch, self._env, after), "store"
            ):
                after = ids[-1]
                for key_id in ids:
                    row = await self._load(key_id)
                    if row is None or row.kek_version != prev.version:
                        continue
                    out: list[str] = []
                    if not self._rewrap_one(row, prev, kek, out):
                        failed.append(row.id)
                        await self._audit(
                            "security.kek_rotation_failed",
                            {**base, "key_id": str(row.id), "done": str(done)},
                        )
                        continue
                    cas = self._store.rewrap(
                        row.id, from_version=prev.version, dek_ref=out[0], kek_version=kek.version
                    )
                    if await self._io(cas, "store"):
                        done += 1
                        m.credential_rewrap_rows_total.inc()
        except BaseException:
            try:  # terminal record for a run that died mid-way (resumable: rows are CAS'd)
                await self._audit(
                    "security.kek_rotation_incomplete",
                    {**base, "rows": str(done), "failed": str(len(failed)), "aborted": "true"},
                )
            except Exception:
                m.credential_outcome_audit_failures_total.inc()
            raise
        left = await self._io(self._store.count_at_kek_version(prev.version, self._env), "store")
        fields = {**base, "rows": str(done), "left": str(left), "failed": str(len(failed))}
        complete = left == 0 and not failed
        action = "security.kek_rotated" if complete else "security.kek_rotation_incomplete"
        await self._audit(action, fields)
        return RewrapReport(prev.version, kek.version, done, left, tuple(failed))

    @staticmethod
    def _rewrap_one(row: CredentialRow, prev: LoadedKek, kek: LoadedKek, out: list[str]) -> bool:
        try:
            dek = prev.unwrap_dek(row.dek_ref, credential_id=row.id)
        except (InvalidTag, ValueError):
            return False
        check = None
        try:
            new_ref = kek.wrap_dek(dek, credential_id=row.id)
            verify = kek.unwrap_dek(new_ref, credential_id=row.id)
            try:
                aad = env.cred_aad(row.env, row.exchange_account_id, row.id, "secret")
                check = env.open_(verify, row.secret_enc, aad)
            finally:
                env.zero(verify)
        except (InvalidTag, ValueError):
            return False
        finally:
            env.zero(dek)
            if check is not None:
                env.zero(check)
        out.append(new_ref)
        return True
