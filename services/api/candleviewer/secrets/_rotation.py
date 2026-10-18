"""KEK lifecycle on top of the broker (E27-T02): KCV verification without trust-on-first-use
and the resumable, verified DEK re-wrap (e27-kek.md §5). Private to M2."""

from __future__ import annotations

from uuid import UUID, uuid4

from cryptography.exceptions import InvalidTag

from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _metrics as m
from candleviewer.secrets._kek import LoadedKek, kcv_matches
from candleviewer.secrets.broker import _SYSTEM, CredentialBroker
from candleviewer.secrets.errors import KekLoadError, KekUnavailable
from candleviewer.secrets.models import CredentialRow, RewrapReport
from candleviewer.secrets.store import AuthKeyStore, KcvStore


class RotatingBroker(CredentialBroker):
    """The broker the service runs: borrow/store/destroy plus KCV and KEK re-wrap."""

    async def verify_kcv(self, kek: LoadedKek, kcvs: KcvStore, *, must_exist: bool) -> None:
        """No trust-on-first-use, inside this process's environment lineage (#2338).

        An unknown KCV is recorded only if no live row exists at that version, or after a
        trial unwrap of one such row succeeds; `must_exist` (previous KEK) refuses unknown.
        An enrolment commits its `security.kek_enrolled` record with the row (#2266), and the
        KCV the store holds afterwards, a concurrent winner's included, is the one checked.
        """
        expected = await self._io(kcvs.kcv_for(self._env, kek.version), "kcv_store_unavailable")
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
            kind, role, _ = _SYSTEM
            fields = {"actor_kind": kind, "actor_role": role, "env": self._env}
            fields |= {"kek_version": str(kek.version), "kcv": kek.kcv().hex()}
            put = kcvs.record_kcv(
                self._env, kek.version, kek.kcv(), audit=("security.kek_enrolled", fields)
            )
            stored, _enrolled = await self._io(put, "kcv_store_unavailable")
            expected = stored
        if not kcv_matches(kek, expected):
            raise KekLoadError("kek_mismatch")

    def staged(self, to_version: int) -> tuple[LoadedKek, LoadedKek]:
        """The current and previous KEK of a rotation to `to_version` this broker was booted for:
        `KekUnavailable` unless they are at `to_version` and `to_version - 1`, `kek_reused` if they
        are one key (a no-op "rotation" must not be recorded). Checked before any latch (#2266)."""
        kek, prev = self._require_kek(), self._prev
        if prev is None or kek.version != to_version or prev.version != kek.version - 1:
            raise KekUnavailable("kek_unavailable")
        if kcv_matches(kek, prev.kcv()):
            raise KekLoadError("kek_reused")
        return kek, prev

    async def rewrap_all(
        self,
        new_kek_version: int,
        *,
        actor: tuple[str, str, str | None] = _SYSTEM,
        batch: int = 50,
        auth_keys: AuthKeyStore | None = None,
    ) -> RewrapReport:
        """Re-wrap every DEK at `new_kek_version - 1` under the current KEK (e27-kek.md §5).

        Ciphertext/nonces untouched; each new wrap is verified by opening `secret_enc` before
        the compare-and-set, which commits the row's `security.credential_rewrapped` with it.
        The run opens with `kek_rotation_resumed` when an earlier run moved rows and rows are
        left, else `kek_rotation_started`; every record carries its `run_id` (#2266). Each
        listed row is re-read and fenced (`_fenced`). Keyset paging terminates; failures are
        audited as they occur; `kek_rotated` only when nothing is left (the environment's auth
        keyring rows in `auth_keys` included) and no row failed, otherwise
        `kek_rotation_incomplete`. With `auth_keys` None (no keyring store wired) the keyring is
        unchecked: `auth_left` reads `unchecked` and the run is never complete (#3505).
        """
        kek, prev = self.staged(new_kek_version)
        run_id = uuid4()
        self._cache.flush()
        total = await self._io(self._store.count_at_kek_version(prev.version, self._env), "store")
        moved = self._store.count_rewrapped_since_enrolment(kek.version, self._env)
        before = await self._io(moved, "store")
        resumed = total > 0 and before > 0  # an earlier run moved rows, and rows are left
        kind, role, user = actor
        base = {
            "run_id": str(run_id),
            "from": str(prev.version),
            "to": str(kek.version),
            "from_kcv": prev.kcv().hex(),
            "to_kcv": kek.kcv().hex(),
            "actor_kind": kind,
            "actor_role": role,
            **({"actor_user_id": user} if user else {}),
        }
        if resumed:
            opened = {"remaining": str(total), "already_rewrapped": str(before)}
            await self._audit("security.kek_rotation_resumed", {**base, **opened})
        else:
            await self._audit("security.kek_rotation_started", {**base, "rows": str(total)})
        # Each moved row's record, committed with its compare-and-set (#2266).
        per_row = {k: base[k] for k in ("run_id", "from", "to")} | {"env": self._env}
        per_row |= {k: v for k, v in base.items() if k.startswith("actor_")}
        done, failed, after = 0, [], None
        try:
            while ids := await self._io(
                self._store.ids_at_kek_version(prev.version, batch, self._env, after), "store"
            ):
                after = ids[-1]
                for key_id in ids:
                    row = await self._load(key_id)
                    if row is None or self._fenced(row, key_id, prev.version):
                        continue
                    out: list[str] = []
                    if not self._rewrap_one(row, prev, kek, out):
                        failed.append(row.id)
                        await self._audit(
                            "security.kek_rotation_failed",
                            {**base, "key_id": str(row.id), "done": str(done)},
                        )
                        continue
                    fields = {
                        **per_row,
                        "key_id": str(row.id),
                        "exchange_account_id": str(row.exchange_account_id),
                    }
                    cas = self._store.rewrap(
                        row.id,
                        env=self._env,
                        from_version=prev.version,
                        dek_ref=out[0],
                        kek_version=kek.version,
                        audit=("security.credential_rewrapped", fields),
                    )
                    if await self._io(cas, "store"):
                        done += 1
                        m.credential_rewrap_rows_total.inc()
            left, auth_left = await self._left(prev.version, auth_keys)
        except BaseException:
            try:  # terminal record for a run that died mid-way (resumable: rows are CAS'd)
                await self._audit(
                    "security.kek_rotation_incomplete",
                    {**base, "rows": str(done), "failed": str(len(failed)), "aborted": "true"},
                )
            except Exception:
                m.credential_outcome_audit_failures_total.inc()
            raise
        left += auth_left or 0
        fields = {
            **base,
            "rows": str(done),
            "left": str(left),
            "auth_left": "unchecked" if auth_left is None else str(auth_left),
            "failed": str(len(failed)),
        }
        complete = left == 0 and not failed and auth_left is not None
        action = "security.kek_rotated" if complete else "security.kek_rotation_incomplete"
        await self._audit(action, fields)
        report = (prev.version, kek.version, done, left, tuple(failed))
        return RewrapReport(*report, run_id=run_id, resumed=resumed, complete=complete)

    async def _left(self, version: int, auth_keys: AuthKeyStore | None) -> tuple[int, int | None]:
        """`(API key rows, auth keyring rows)` of this environment still at `version`: the rows
        `ids_at_kek_version` lists, and those of `auth_keys`, None (unchecked) without one."""
        api = await self._io(self._store.count_at_kek_version(version, self._env), "store")
        if auth_keys is None:
            return api, None
        return api, await self._io(auth_keys.count_at_kek_version(version, self._env), "store")

    def _fenced(self, row: CredentialRow, key_id: UUID, version: int) -> bool:
        """The round-5 fence (#2266): a row revoked by either signal, destroyed in this process
        or no longer at `version` is never re-wrapped. Every other status is (0017 `key_status`),
        or the rotation could never complete."""
        if row.revoked or row.status == "revoked" or key_id in self._destroyed:
            return True
        return row.kek_version != version

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
