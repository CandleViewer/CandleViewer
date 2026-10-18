"""KEK rotation and KCV policy on the broker (E27-T02, e27-kek.md §5)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from candleviewer.secrets._rotation import RotatingBroker as CredentialBroker
from candleviewer.secrets.errors import (
    KekLoadError,
    KekUnavailable,
)
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.store import InMemoryCredentialStore
from tests.unit.credentials_m2._helpers import _borrow, _store
from tests.unit.credentials_m2._vectors import (
    ACCOUNT,
    KEK_LIVE,
    KEK_V1,
    KEK_V2,
    SNAPSHOT,
    AuditLog,
    kek,
)


async def _seed(n: int) -> tuple[InMemoryCredentialStore, list[Any], dict[Any, bytes]]:
    s = InMemoryCredentialStore()
    b = CredentialBroker(s, AuditLog(), kek(KEK_V1, 1))
    metas = [await _store(b, f"KEY{i:04d}ABCDEFGH") for i in range(n)]
    return s, metas, {m.key_id: s.rows[m.key_id]["secret_enc"] for m in metas}


def _rot(s: InMemoryCredentialStore, audit: AuditLog | None = None) -> CredentialBroker:
    return CredentialBroker(s, audit or AuditLog(), kek(KEK_V2, 2), prev_kek=kek(KEK_V1, 1))


async def test_rewrap_all_keeps_ciphertext_and_bumps_version() -> None:
    s, metas, before = await _seed(20)
    old_refs = {k: s.rows[k]["dek_ref"] for k in before}
    audit = AuditLog()
    rep = await _rot(s, audit).rewrap_all(2, batch=7)
    assert (rep.rewrapped, rep.remaining, rep.failed) == (20, 0, ())
    for m in metas:
        row = s.rows[m.key_id]
        assert row["kek_version"] == 2 and row["secret_enc"] == before[m.key_id]
        assert row["dek_ref"] != old_refs[m.key_id]
    only_v2 = CredentialBroker(s, AuditLog(), kek(KEK_V2, 2))
    for i, m in enumerate(metas):
        assert (await _borrow(only_v2, m.key_id))[0] == f"KEY{i:04d}ABCDEFGH"
    assert audit.actions() == ["security.kek_rotation_started", "security.kek_rotated"]
    started = audit.records[0][1]
    assert started["from_kcv"] == kek(KEK_V1).kcv().hex() and started["rows"] == "20"
    assert (await _rot(s).rewrap_all(2)).rewrapped == 0  # idempotent


async def test_borrow_mid_rotation_uses_prev_kek() -> None:
    s, metas, _ = await _seed(2)
    b = _rot(s)
    assert (await _borrow(b, metas[0].key_id))[0] == "KEY0000ABCDEFGH"


async def test_rewrap_all_resumes_after_kill_and_borrows_in_between() -> None:
    s, metas, _ = await _seed(20)

    class Killed(asyncio.CancelledError):
        """A kill mid-run (cancellation is not mapped to a typed error)."""

    calls = 0
    real = s.rewrap

    async def dying(key_id: Any, **kw: Any) -> bool:
        nonlocal calls
        if calls == 8:
            raise Killed
        calls += 1
        return await real(key_id, **kw)

    s.rewrap = dying  # type: ignore[method-assign]  # inject a crash after 8 rows
    with pytest.raises(Killed):
        await _rot(s).rewrap_all(2)
    assert [r["kek_version"] for r in s.rows.values()].count(2) == 8
    mixed = _rot(s)  # borrow after a partial rewrap: both versions decrypt
    for i, m in enumerate(metas):
        assert (await _borrow(mixed, m.key_id))[0] == f"KEY{i:04d}ABCDEFGH"
    s.rewrap = real  # type: ignore[method-assign]  # restart
    rep = await _rot(s).rewrap_all(2)
    assert rep.rewrapped == 12 and rep.remaining == 0
    only_v2 = CredentialBroker(s, AuditLog(), kek(KEK_V2, 2))
    for m in metas:
        await _borrow(only_v2, m.key_id)


async def test_rewrap_all_requires_both_keks() -> None:
    s, _, _ = await _seed(1)
    with pytest.raises(KekUnavailable):
        await CredentialBroker(s, AuditLog(), kek(KEK_V2, 2)).rewrap_all(2)
    with pytest.raises(KekUnavailable):
        await CredentialBroker(s, AuditLog(), kek(KEK_V2, 3), prev_kek=kek(KEK_V1, 1)).rewrap_all(3)


async def test_rewrap_bad_rows_reported_and_audited() -> None:
    s, metas, _ = await _seed(3)
    s.rows[metas[1].key_id]["dek_ref"] = "v2:" + bytes(40).hex()
    audit = AuditLog()
    rep = await _rot(s, audit).rewrap_all(2, batch=1)
    assert rep.rewrapped == 2 and rep.failed == (metas[1].key_id,) and rep.remaining == 1
    assert audit.actions() == [
        "security.kek_rotation_started",
        "security.kek_rotation_failed",
        "security.kek_rotation_incomplete",
    ]
    failed = audit.records[1][1]
    assert failed["key_id"] == str(metas[1].key_id) and failed["done"] in {"0", "1", "2"}
    assert audit.records[2][1]["left"] == "1"


async def test_rewrap_terminates_when_cas_never_moves_row() -> None:
    s, _, _ = await _seed(3)

    async def never(key_id: Any, **kw: Any) -> bool:
        return False

    s.rewrap = never  # type: ignore[method-assign]  # another worker / filter mismatch
    audit = AuditLog()
    rep = await asyncio.wait_for(_rot(s, audit).rewrap_all(2, batch=2), timeout=5)
    assert rep.rewrapped == 0 and rep.remaining == 3
    assert audit.actions()[-1] == "security.kek_rotation_incomplete"


async def test_rewrap_skips_row_moved_or_vanished() -> None:
    s, metas, _ = await _seed(2)
    s.rows[metas[0].key_id]["kek_version"] = 2
    orig_ids, orig_get = s.ids_at_kek_version, s.get
    calls = 0

    async def stale(version: int, limit: int, env: str, after: Any = None) -> list[Any]:
        nonlocal calls
        calls += 1
        return sorted(m.key_id for m in metas) if calls == 1 else []

    async def get(key_id: Any, env: str) -> Any:
        return None if key_id == metas[1].key_id else await orig_get(key_id, env)

    s.ids_at_kek_version, s.get = stale, get  # type: ignore[method-assign]  # inject stale listing
    assert (await _rot(s).rewrap_all(2)).rewrapped == 0
    s.ids_at_kek_version, s.get = orig_ids, orig_get  # type: ignore[method-assign]


async def test_kcv_recorded_when_no_rows_at_version(store: Any) -> None:
    b = CredentialBroker(store, AuditLog(), kek())
    await b.verify_kcv(kek(), store, must_exist=False)
    assert store.kcvs[("demo", 1)] == kek().kcv()
    await b.verify_kcv(kek(), store, must_exist=False)  # matches now


async def test_kcv_wrong_kek_not_pinned_when_rows_exist() -> None:
    s, _, _ = await _seed(1)  # rows at v1, no KCV yet (0020 on a populated DB)
    wrong = kek(KEK_V2, 1)
    with pytest.raises(KekLoadError) as ei:
        await CredentialBroker(s, AuditLog(), wrong).verify_kcv(wrong, s, must_exist=False)
    assert ei.value.reason == "kek_mismatch" and s.kcvs == {}
    right = kek(KEK_V1, 1)
    await CredentialBroker(s, AuditLog(), right).verify_kcv(right, s, must_exist=False)
    assert s.kcvs[("demo", 1)] == right.kcv()


async def test_kcv_mismatch_and_prev_must_exist(store: Any) -> None:
    store.kcvs[("demo", 1)] = kek(KEK_V2).kcv()
    with pytest.raises(KekLoadError):
        await CredentialBroker(store, AuditLog(), kek()).verify_kcv(kek(), store, must_exist=False)
    with pytest.raises(KekLoadError):
        await CredentialBroker(store, AuditLog(), kek()).verify_kcv(
            kek(KEK_V1, 5), store, must_exist=True
        )


async def test_kcv_trial_unwrap_row_vanished() -> None:
    s, _, _ = await _seed(1)

    async def gone(key_id: Any, env: str) -> Any:
        return None

    s.get = gone  # type: ignore[method-assign]
    with pytest.raises(KekLoadError):
        await CredentialBroker(s, AuditLog(), kek()).verify_kcv(kek(), s, must_exist=False)


async def test_kcv_concurrent_record_returns_winner(store: Any) -> None:
    store.kcvs[("demo", 1)] = kek(KEK_V2).kcv()
    assert await store.record_kcv("demo", 1, kek().kcv()) == kek(KEK_V2).kcv()


async def test_rewrap_refuses_reused_kek() -> None:
    s, _, _ = await _seed(1)
    b = CredentialBroker(s, AuditLog(), kek(KEK_V1, 2), prev_kek=kek(KEK_V1, 1))
    with pytest.raises(KekLoadError) as ei:
        await b.rewrap_all(2)
    assert ei.value.reason == "kek_reused"


async def test_rewrap_records_actor() -> None:
    s, _, _ = await _seed(1)
    audit = AuditLog()
    await _rot(s, audit).rewrap_all(2, actor=("user", "owner", "u-1"))
    assert all(f["actor_user_id"] == "u-1" for _, f in audit.records)


async def test_rewrap_new_wrap_verified_before_cas(monkeypatch: pytest.MonkeyPatch) -> None:
    s, metas, _ = await _seed(1)
    s.rows[metas[0].key_id]["secret_enc"] = bytes(40)  # ciphertext the new wrap cannot open
    s.rows[metas[0].key_id]["enc_nonce"] = bytes(12)
    rep = await _rot(s).rewrap_all(2)
    assert rep.failed == (metas[0].key_id,) and s.rows[metas[0].key_id]["kek_version"] == 1


async def test_rewrap_aborted_run_writes_terminal_record() -> None:
    s, _, _ = await _seed(3)
    audit = AuditLog()

    async def boom(key_id: Any, **kw: Any) -> bool:
        raise RuntimeError("db")

    s.rewrap = boom  # type: ignore[method-assign]
    with pytest.raises(Exception):  # noqa: B017 -- typed or raw, it must propagate
        await _rot(s, audit).rewrap_all(2)
    assert audit.actions()[-1] == "security.kek_rotation_incomplete"
    assert audit.records[-1][1]["aborted"] == "true"


async def test_rotation_ignores_other_environment_rows() -> None:
    """C-2.11: on a shared DB a demo rotation neither counts nor touches live rows, so `left`
    reaches 0 and the run is `kek_rotated`; the KCV trial unwrap never picks a live row."""
    s, metas, _ = await _seed(2)  # demo rows
    live = CredentialBroker(s, AuditLog(), kek(KEK_LIVE, 1, "live"), env_name="live")
    lm = await live.store("live", ACCOUNT, "l", Secret("LIVEKEY00000ABCD"), Secret("s"), SNAPSHOT)
    audit = AuditLog()
    rep = await _rot(s, audit).rewrap_all(2)
    assert (rep.rewrapped, rep.remaining) == (2, 0)
    assert audit.actions()[-1] == "security.kek_rotated"
    assert s.rows[lm.key_id]["kek_version"] == 1  # live row untouched
    del metas


_REWRAPPED = "security.credential_rewrapped"


def _cas(s: InMemoryCredentialStore, key_id: Any, **kw: Any) -> Any:
    """The compare-and-set of a run moving `key_id` from v1 to v2, with its row record."""
    args: dict[str, Any] = {"env": "demo", "from_version": 1, "dek_ref": "v1:00", "kek_version": 2}
    return s.rewrap(key_id, **(args | kw), audit=(_REWRAPPED, {"key_id": str(key_id)}))


async def test_rewrap_all_commits_one_credential_rewrapped_with_each_moved_row() -> None:
    """#2266: the row record goes with the row's compare-and-set, never through the WAL sink; a
    row whose new wrap fails is not moved and gets none."""
    s, metas, _ = await _seed(3)
    s.rows[metas[1].key_id]["dek_ref"] = "v2:" + bytes(40).hex()  # its re-wrap fails
    audit = AuditLog()
    await _rot(s, audit).rewrap_all(2, actor=("user", "owner", "u-1"), batch=2)
    moved = sorted(str(k) for k, row in s.rows.items() if row["kek_version"] == 2)
    assert len(moved) == 2 and sorted(f["key_id"] for _, f in s.rewrap_audit) == moved
    (run_id,) = {f["run_id"] for _, f in s.rewrap_audit}
    row = {"run_id": run_id, "key_id": str(metas[0].key_id), "exchange_account_id": str(ACCOUNT)}
    who = {"actor_kind": "user", "actor_role": "owner", "actor_user_id": "u-1"}
    expected = {**row, "env": "demo", "from": "1", "to": "2", **who}
    assert (_REWRAPPED, expected) in s.rewrap_audit and _REWRAPPED not in audit.actions()


async def test_rewrap_cas_writes_its_record_iff_it_moves_the_row() -> None:
    s, metas, _ = await _seed(1)
    key = metas[0].key_id
    assert not await _cas(s, key, from_version=2)  # stale
    assert not await _cas(s, key, env="live")  # not the process's environment
    assert s.rewrap_audit == []
    assert await _cas(s, key) is True
    assert not await _cas(s, key)  # a replay: the row has moved on
    assert s.rewrap_audit == [(_REWRAPPED, {"key_id": str(key)})]


@pytest.mark.parametrize(
    "revoked", [{"revoked": True}, {"status": "revoked"}], ids=["revoked_at", "status"]
)
async def test_rewrap_cas_on_a_revoked_row_moves_nothing_and_writes_nothing(
    revoked: dict[str, Any],
) -> None:
    """Either revocation signal fences the row, as the Postgres CAS predicate does."""
    s, metas, _ = await _seed(1)
    key = metas[0].key_id
    s.rows[key].update(revoked)
    before = dict(s.rows[key])
    assert not await _cas(s, key)
    assert s.rows[key] == before and s.rewrap_audit == []
