"""`InMemoryExportKeyStore`, the `ExportKeyStore` fake M2's tests use (#889 S4b, ADR-0039), one
behaviour each. `REFUSED` is what every `ExportKeyStore` refuses before any change or I/O, and the
records and helpers here serve every store's tests. Placeholder bytes, never key material."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any
from uuid import UUID, uuid4

import pytest

from candleviewer.secrets.store import EXPORT_KEY_PUBLIC, EXPORT_KEY_SEALED, InMemoryExportKeyStore

Store = InMemoryExportKeyStore
T0 = datetime(2026, 9, 1, tzinfo=UTC)
SEED, WRAP, NEXT_WRAP = b"\x5a" * 60, "ek1:" + "ab" * 60, "ek1:" + "cd" * 60
OWNER, OTHER = UUID(int=1), UUID(int=2)
#: Placeholder records `(action, fields)`: a store never reads them. S6a-2 registers the boot's
#: actions and writes their real fields; S7 the rotation's.
GENERATED = ("security.audit_signing_key_generated", {"key": "first"})
ROTATED = ("security.audit_signing_key_rotated", {"key": "next"})
REWRAPPED = ("security.audit_signing_key_rewrapped", {"key": "moved"})
DESTROYED = ("security.audit_signing_key_material_destroyed", {"key": "gone"})
RETIRED = ["retired", "scheduled", None]  # status, retired_reason, sealed_seed (Q3)


def key_id(version: int, pk: bytes | None = None) -> str:
    fp = hashlib.sha256(pk or bytes([version]) * 32).hexdigest()
    return f"cv-audit-export-v{version}:{fp[:16]}"


def export_key(
    version: int, *, env: str = "demo", pk: bytes | None = None, **request: Any
) -> dict[str, Any]:
    """A valid record of key `version`, its public key `pk` (32 bytes of `version` by default)."""
    pk = pk or bytes([version]) * 32
    sealed = {"sealed_seed": SEED, "dek_ref": WRAP, "kek_version": 1}
    named = {"id": uuid4(), "env": env, "version": version, "key_id": key_id(version, pk)}
    return named | {"public_key": pk} | sealed | request


def rotation_request(owner: UUID = OWNER, ref: str | None = None) -> dict[str, Any]:
    """A rotation's request: its Owner, `Idempotency-Key` and request fingerprint."""
    return {"created_by": owner, "client_ref": ref or str(uuid4()), "client_body_sha256": "a" * 64}


def days() -> Callable[[], datetime]:
    """A clock a day further on at each read, from `T0`."""
    ticks = count()
    return lambda: T0 + timedelta(days=next(ticks))


@pytest.fixture
async def keys() -> Store:
    """A demo store holding its first key, v1, generated at `T0`."""
    store = Store(clock=days())
    assert await store.insert_first(export_key(1), audit=GENERATED) is True
    return store


async def _rotate(
    store: Store, version: int = 2, *, retire: int = 0, pk: bytes | None = None, **req: Any
) -> dict[str, Any] | None:
    """Key `version` made active by a rotation of key `retire` (the one before it by default)."""
    record = export_key(version, env=store.env, pk=pk, **(req or rotation_request()))
    retiring = key_id(retire or version - 1)
    return await store.rotate(record, retire=retiring, reason="scheduled", audit=ROTATED)


Call = Callable[[Any], Awaitable[object]]
#: A re-wrap of v1 from KEK v1 to v2, with its record, which every re-wrap carries (security F1).
MOVE: dict[str, Any] = {"env": "demo", "from_version": 1, "dek_ref": NEXT_WRAP, "kek_version": 2}
MOVE["audit"] = REWRAPPED


def _rotating(record: dict[str, Any], reason: str = "scheduled") -> Call:
    return lambda s: s.rotate(record, retire=key_id(1), reason=reason, audit=ROTATED)


def _first(record: dict[str, Any]) -> Call:
    return lambda s: s.insert_first(record, audit=GENERATED)


#: What every `ExportKeyStore` refuses (`ValueError`) before any change or I/O: another
#: environment, a plaintext seed or DEK, a first key not v1, an incomplete request, a reason or
#: an `Idempotency-Key` the table cannot hold, a malformed `retire` or `key_id`, and a re-wrap's
#: KEK version that is not an int of at least 1 or that moves nothing (I3).
REFUSED: dict[str, Call] = {
    "env_active": lambda s: s.active("live"),
    "env_list": lambda s: s.list_keys("live"),
    "env_rotation": lambda s: s.rotation("live", created_by=OWNER, client_ref=str(uuid4())),
    "env_count": lambda s: s.count_at_kek_version(1, "live"),
    "env_rewrap": lambda s: s.rewrap(key_id(1), **MOVE | {"env": "live"}),
    "env_retained": lambda s: s.count_retired_with_seed("live"),
    "env_destroy": lambda s: s.destroy_retired_seeds("live", audit=DESTROYED),
    "env_first": _first(export_key(1, env="live")),
    "env_rotate": _rotating(export_key(2, env="live", **rotation_request())),
    "first_not_v1": _first(export_key(2)),
    "plaintext_seed": _first(export_key(1) | {"sealed_seed": bytes(32)}),
    "plaintext_dek": _first(export_key(1) | {"dek_ref": bytes(32).hex()}),
    "dek_newline": _rotating(export_key(2, **rotation_request()) | {"dek_ref": NEXT_WRAP + "\n"}),
    "no_request": _rotating(export_key(2)),
    "ref_no_uuid": _rotating(export_key(2, **rotation_request(ref="not-a-uuid"))),
    "reason": _rotating(export_key(2, **rotation_request()), reason="expired"),
    "rewrap_plaintext": lambda s: s.rewrap(key_id(1), **MOVE | {"dek_ref": bytes(32).hex()}),
    "rotation_ref": lambda s: s.rotation("demo", created_by=OWNER, client_ref="nope"),
    "retire_not_a_key_id": lambda s: s.rotate(
        export_key(2, **rotation_request()), retire=str(uuid4()), reason="scheduled", audit=ROTATED
    ),
    "rewrap_not_a_key_id": lambda s: s.rewrap(str(uuid4()), **MOVE),
    "rewrap_key_id_not_str": lambda s: s.rewrap(1, **MOVE),
    "rewrap_key_id_v0": lambda s: s.rewrap(f"cv-audit-export-v0:{'a' * 16}", **MOVE),
    "rewrap_key_id_v01": lambda s: s.rewrap(f"cv-audit-export-v01:{'a' * 16}", **MOVE),
    "rewrap_key_id_upper": lambda s: s.rewrap(key_id(1).upper(), **MOVE),
    "rewrap_from_version_0": lambda s: s.rewrap(key_id(1), **MOVE | {"from_version": 0}),
    "rewrap_from_version_str": lambda s: s.rewrap(key_id(1), **MOVE | {"from_version": "1"}),
    "rewrap_from_version_true": lambda s: s.rewrap(key_id(1), **MOVE | {"from_version": True}),
    "rewrap_kek_version_true": lambda s: s.rewrap(
        key_id(1), **MOVE | {"from_version": 2, "kek_version": True}
    ),
    "rewrap_kek_version_0": lambda s: s.rewrap(key_id(1), **MOVE | {"kek_version": 0}),
    "rewrap_kek_version_str": lambda s: s.rewrap(key_id(1), **MOVE | {"kek_version": "2"}),
    "rewrap_same_version": lambda s: s.rewrap(key_id(1), **MOVE | {"kek_version": 1}),
    "rewrap_no_move": lambda s: s.rewrap(key_id(1), **MOVE | {"kek_version": 1, "dek_ref": WRAP}),
}


@pytest.mark.parametrize("call", REFUSED.values(), ids=list(REFUSED))
async def test_a_refused_call_changes_nothing(keys: Store, call: Call) -> None:
    before = copy.deepcopy((keys.rows, keys.audit))
    with pytest.raises(ValueError):
        await call(keys)
    assert (keys.rows, keys.audit) == before


def _reusing_ids(s: Store) -> Awaitable[object]:
    """A rotation whose new key reuses the active key's primary key."""
    return _rotating(export_key(2, **rotation_request()) | {"id": s.rows[0]["id"]})(s)


#: What the table refuses (21 Sec.3.1.5b), and so the fake: its CHECKs, which Postgres fires before
#: any unique key, a reused primary key, and a re-wrap that moves the KEK version but keeps the DEK,
#: which the write-once trigger refuses (23514 naming `kek_version`).
TABLE_REFUSED: dict[str, Call] = {
    "key_id_not_derived": _first(export_key(1) | {"key_id": key_id(1, bytes(32))}),
    "public_key_short": _first(export_key(1) | {"public_key": bytes(31)}),
    "kek_version_0": _first(export_key(1) | {"kek_version": 0}),
    "body_hash_not_hex": _rotating(
        export_key(2, **rotation_request()) | {"client_body_sha256": "A" * 64}
    ),
    "reused_id": _reusing_ids,
    "rewrap_same_dek": lambda s: s.rewrap(key_id(1), **MOVE | {"dek_ref": WRAP}),
    "reused_first_id": lambda s: s.insert_first(
        export_key(1) | {"id": s.rows[0]["id"]}, audit=GENERATED
    ),  # the primary key, before `insert_first`'s False for a key already held
}


@pytest.mark.parametrize("call", TABLE_REFUSED.values(), ids=list(TABLE_REFUSED))
async def test_the_fake_refuses_what_the_table_refuses(keys: Store, call: Call) -> None:
    """Against a store that already holds v1: a CHECK comes before `insert_first`'s False."""
    before = copy.deepcopy((keys.rows, keys.audit))
    with pytest.raises(ValueError):
        await call(keys)
    assert (keys.rows, keys.audit) == before


async def test_list_keys_gives_public_records_only_newest_first(keys: Store) -> None:
    await _rotate(keys, 2)
    await _rotate(keys, 3)
    listed = await keys.list_keys("demo")
    assert [(r["version"], r["status"]) for r in listed] == [
        (3, "active"), (2, "retired"), (1, "retired")
    ]  # fmt: skip
    assert {tuple(r) for r in listed} == {EXPORT_KEY_PUBLIC}  # no `sealed_seed`, no `dek_ref`


async def test_active_is_the_sealed_record_s6_opens(keys: Store) -> None:
    sealed = await keys.active("demo")
    assert sealed is not None and tuple(sealed) == EXPORT_KEY_SEALED
    assert (sealed["env"], sealed["key_id"], sealed["sealed_seed"]) == ("demo", key_id(1), SEED)


async def test_insert_first_inserts_one_first_key_with_its_record(keys: Store) -> None:
    assert await keys.insert_first(export_key(1, pk=bytes(32)), audit=GENERATED) is False
    assert [(r["key_id"], r["valid_from"]) for r in keys.rows] == [(key_id(1), T0)]
    assert keys.audit == [GENERATED]  # the losing boot's record is not committed


async def test_a_rotation_retires_destroys_and_activates_at_its_records_time(keys: Store) -> None:
    ref = str(UUID(int=7))
    made = await _rotate(keys, 2, **rotation_request(ref=ref.upper()))
    old, new = keys.rows
    assert [old[c] for c in ("status", "retired_reason", "sealed_seed")] == RETIRED
    assert old["valid_until"] == new["valid_from"] == T0 + timedelta(days=1)
    assert [new[c] for c in ("status", "sealed_seed", "client_ref")] == ["active", SEED, ref]
    assert keys.audit == [GENERATED, ROTATED]
    assert made is not None and made["active"]["key_id"] == key_id(2)
    assert made["retired"]["valid_until"] == made["active"]["valid_from"]


async def test_a_replayed_retire_of_a_retired_key_changes_nothing(keys: Store) -> None:
    await _rotate(keys, 2)
    before = copy.deepcopy((keys.rows, keys.audit))
    assert await _rotate(keys, 3, retire=1) is None  # v1 is retired: no rotation, as in SQL
    assert (keys.rows, keys.audit) == before


async def test_a_rotation_steps_from_the_highest_version_not_the_active_ones(keys: Store) -> None:
    pk = bytes([3]) * 32
    gone = {
        "status": "retired",
        "valid_until": T0,
        "retired_reason": "scheduled",
        "sealed_seed": None,
    }
    v3 = {"id": uuid4(), "version": 3, "key_id": key_id(3), "public_key": pk}
    keys.rows.append(
        keys.rows[0] | v3 | {"fingerprint_sha256": hashlib.sha256(pk).hexdigest()} | gone
    )
    before = copy.deepcopy((keys.rows, keys.audit))
    with pytest.raises(ValueError, match="by one"):
        await _rotate(keys, 2)  # v1 is active, but v3 is the highest: the next is v4
    assert (keys.rows, keys.audit) == before


async def test_a_reused_request_is_refused_as_its_unique_key_refuses_it(keys: Store) -> None:
    request = rotation_request()
    await _rotate(keys, 2, **request)
    before = copy.deepcopy((keys.rows, keys.audit))
    with pytest.raises(ValueError, match="unique") as taken:
        await _rotate(keys, 3, **request)  # the same Owner and Idempotency-Key, a new rotation
    assert (keys.rows, keys.audit) == before
    assert (
        getattr(taken.value, "code", None) == "STORAGE_EXPORT_KEY_REQUEST_TAKEN"
    )  # as in M10 (I1)


@pytest.mark.parametrize(("version", "steps"), [(2, True), (3, False), (1, False)])
async def test_a_rotation_steps_the_version_by_one(keys: Store, version: int, steps: bool) -> None:
    if steps:
        assert await _rotate(keys, version, retire=1) is not None
        return
    with pytest.raises(ValueError, match="by one"):
        await _rotate(keys, version, retire=1, pk=bytes(32))


def _stop_clock(store: Store) -> None:
    def stopped() -> datetime:
        raise RuntimeError("no clock")

    store.clock = stopped


def _fail_audit(store: Store) -> None:
    store.audit_fails = True


@pytest.mark.parametrize(
    ("arrange", "rotation", "refused"),
    [
        (_stop_clock, {}, RuntimeError),  # 1. its record's time cannot be taken
        (None, {"retire": 9}, None),  # 2. `retire` is not the active key: no rotation
        (None, {"version": 3, "retire": 1}, ValueError),  # 3. a version gap
        (None, {"pk": bytes([1]) * 32}, ValueError),  # 3. the new key repeats v1's fingerprint
        (_fail_audit, {}, RuntimeError),  # 4. its record is not written
    ],
    ids=["record_time", "stale", "version", "insert", "audit"],
)
async def test_a_rotation_failing_at_any_step_changes_nothing(
    keys: Store,
    arrange: Callable[[Store], None] | None,
    rotation: dict[str, Any],
    refused: type[Exception] | None,
) -> None:
    before = copy.deepcopy((keys.rows, keys.audit))
    if arrange is not None:
        arrange(keys)
    if refused is None:
        assert await _rotate(keys, **rotation) is None
    else:
        with pytest.raises(refused):
            await _rotate(keys, **rotation)
    assert (keys.rows, keys.audit) == before


async def test_a_rotation_is_rebuilt_as_it_was_made_at_any_age(keys: Store) -> None:
    ref = str(uuid4())
    made = await _rotate(keys, 2, **rotation_request(ref=ref))
    await _rotate(keys, 3)  # days later, the key that rotation made retires in turn
    assert keys.rows[1]["status"] == "retired"
    rebuilt = await keys.rotation("demo", created_by=OWNER, client_ref=ref)
    assert rebuilt is not None and rebuilt == made and rebuilt["active"]["status"] == "active"
    assert rebuilt["client_body_sha256"] == "a" * 64  # the caller compares it (409 on a mismatch)


async def test_another_users_or_environments_request_answers_as_missing(keys: Store) -> None:
    ref, live_only = str(uuid4()), str(uuid4())
    await _rotate(keys, 2, **rotation_request(ref=ref))
    live = Store("live", clock=days())
    await live.insert_first(export_key(1, env="live"), audit=GENERATED)
    await _rotate(live, 2, **rotation_request(ref=ref))  # the same Owner and key, in live
    await _rotate(live, 3, **rotation_request(ref=live_only))
    keys.rows += live.rows  # one table holds both environments' keys
    assert await keys.rotation("demo", created_by=OTHER, client_ref=ref) is None
    assert await keys.rotation("demo", created_by=OWNER, client_ref=live_only) is None
    mine = await keys.rotation("demo", created_by=OWNER, client_ref=ref.upper())  # canonical
    assert mine is not None and mine["active"]["env"] == "demo"


async def test_the_rewrap_compares_and_sets_on_keys_holding_their_seed(keys: Store) -> None:
    await _rotate(keys, 2)  # v1 retired, its seed destroyed
    move = MOVE  # from KEK v1 to v2, with its record
    assert [await keys.count_at_kek_version(v, "demo") for v in (1, 2)] == [1, 0]  # v2 only
    assert not await keys.rewrap(key_id(1), **move)  # no seed: nothing to re-wrap (Q3)
    assert not await keys.rewrap(key_id(2), **move | {"from_version": 3})  # stale
    assert await keys.rewrap(key_id(2), **move) is True
    assert not await keys.rewrap(key_id(2), **move)  # a replay: it has moved on
    assert [(r["kek_version"], r["dek_ref"]) for r in keys.rows] == [(1, WRAP), (2, NEXT_WRAP)]
    assert [await keys.count_at_kek_version(v, "demo") for v in (1, 2)] == [0, 1]


async def test_a_retired_key_holding_its_seed_counts_until_its_destroy(keys: Store) -> None:
    await _rotate(keys, 2)
    keys.rows[0]["sealed_seed"] = SEED  # a retire that kept the seed, which the table admits
    assert await keys.count_retired_with_seed("demo") == 1  # Q3's `retired_with_seed`
    assert await keys.count_at_kek_version(1, "demo") == 2  # a KEK re-wrap waits for it (I2)
    assert await keys.destroy_retired_seeds("demo", audit=DESTROYED) == 1
    assert await keys.count_retired_with_seed("demo") == 0
    assert await keys.destroy_retired_seeds("demo", audit=DESTROYED) == 0  # nothing left
    assert [r["sealed_seed"] for r in keys.rows] == [None, SEED]  # the active key keeps its own


async def test_a_stale_rotation_is_none_before_its_inserts_checks(keys: Store) -> None:
    """As in SQL: the retire matches no key, so no INSERT runs and no CHECK fires (F2)."""
    bad = export_key(2, **rotation_request()) | {"kek_version": 0}
    assert await keys.rotate(bad, retire=key_id(9), reason="scheduled", audit=ROTATED) is None


async def test_a_rewrap_and_a_destroy_commit_with_their_record_or_not_at_all(keys: Store) -> None:
    await _rotate(keys, 2)
    keys.rows[0]["sealed_seed"] = SEED  # a retire that kept the seed, which the table admits
    keys.audit_fails, before = True, copy.deepcopy((keys.rows, keys.audit))
    for call in (
        keys.rewrap(key_id(2), **MOVE),
        keys.destroy_retired_seeds("demo", audit=DESTROYED),
    ):
        with pytest.raises(RuntimeError):
            await call
    assert (keys.rows, keys.audit) == before
    keys.audit_fails = False
    assert await keys.rewrap(key_id(2), **MOVE) is True
    assert await keys.destroy_retired_seeds("demo", audit=DESTROYED) == 1
    assert await keys.destroy_retired_seeds("demo", audit=DESTROYED) == 0  # no record for none
    assert keys.audit[-2:] == [REWRAPPED, DESTROYED]
    assert [(r["sealed_seed"], r["dek_ref"]) for r in keys.rows] == [
        (None, WRAP),
        (SEED, NEXT_WRAP),
    ]
