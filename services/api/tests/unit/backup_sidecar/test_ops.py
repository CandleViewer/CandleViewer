"""#3319 B1b (ADR-0041 sections 1 and 3; 24 §15.8): the sidecar's ops against a real backup root
under `tmp_path`, its own record and its floor. `plan` mints, `verify` checks the location its
record holds on one descriptor and records the outcome, `remove` quarantines (never the newest
of a kind), `run` and `restore` answer until B1c and B2."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from cvbackup import age_format, protocol, tasks
from cvbackup.ledger import FILE, Ledger, timestamp
from cvbackup.ops import OpError
from cvbackup.paths import LEDGER_DIR, QUARANTINE_DIR, Root
from tests.unit.backup_sidecar._sidecar import (
    T0,
    Sidecar,
    age_bytes,
    build,
    config,
    exists,
    mode,
    read,
    recipient,
    write,
)


async def _sidecar(tmp_path: Path, sock: str, **changes: Any) -> Sidecar:
    return await build(config(tmp_path, sock, **changes))


async def _refused(code: str, sidecar: Sidecar, op: str, **args: str) -> None:
    with pytest.raises(OpError) as refused:
        await sidecar.handle(op, **args)
    assert refused.value.code == code


def _entries(sidecar: Sidecar) -> list[dict[str, Any]]:
    lines = read(Path(sidecar.root.path, LEDGER_DIR, FILE)).splitlines()
    return [cast(dict[str, Any], protocol.loads(line)) for line in lines]


# -- plan ------------------------------------------------------------------------------------


async def test_plan_mints_location_under_root_for_kind(tmp_path: Path, sock: str) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    for kind in ("pg_dump", "config_bundle"):
        result = await sidecar.handle("plan", kind=kind)
        location = str(result["location"])
        assert protocol.is_location(location) and sidecar.root.relative(location) is not None
        assert location.startswith(f"{sidecar.root.path}/{kind}/")
        assert result["encrypted"] is True
        assert result["encryption_ref"] == age_format.fingerprint(sidecar.config.recipient)
    assert _entries(sidecar) == []  # a plan records nothing and spends no run


async def test_plan_unsupported_kind_is_kind_not_supported(tmp_path: Path, sock: str) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    for kind in ("pg_basebackup", "questdb_snapshot", "parquet_sync"):
        await _refused("kind_not_supported", sidecar, "plan", kind=kind)


async def test_plan_recipient_not_matching_pin_is_recipient_mismatch(
    tmp_path: Path, sock: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock, pin=age_format.fingerprint(recipient()))
    await _refused("recipient_mismatch", sidecar, "plan", kind="pg_dump")


async def test_floor_runs_over_cap_in_window_are_runs_capped(tmp_path: Path, sock: str) -> None:
    sidecar = await _sidecar(tmp_path, sock, run_cap=2, run_window=timedelta(hours=1))
    for _ in range(2):
        await sidecar.ledger.append("started", str(uuid.uuid4()), kind="pg_dump")
    await _refused("runs_capped", sidecar, "plan", kind="pg_dump")
    sidecar.clock.advance(hours=1)  # the window rolls past both
    assert (await sidecar.handle("plan", kind="config_bundle"))["encrypted"] is True


async def test_floor_run_cap_survives_restart(tmp_path: Path, sock: str) -> None:
    sidecar = await _sidecar(tmp_path, sock, run_cap=1)
    await sidecar.ledger.append("started", str(uuid.uuid4()), kind="pg_dump")
    sidecar.ledger.close()
    restarted = await build(sidecar.config, sidecar.clock)
    assert restarted.ledger.readable
    await _refused("runs_capped", restarted, "plan", kind="pg_dump")


# -- run and restore (B1c, B2) ---------------------------------------------------------------


async def test_run_checks_its_request_then_answers_tool_failed_in_b1b(
    tmp_path: Path, sock: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    location = str((await sidecar.handle("plan", kind="pg_dump"))["location"])
    fresh = {"backup_id": str(uuid.uuid4()), "kind": "pg_dump", "location": location}
    await _refused("tool_failed", sidecar, "run", **fresh)
    assert _entries(sidecar) == [] and not exists(location)  # no run spent, no file
    other_kind = {**fresh, "kind": "config_bundle"}
    await _refused("bad_request", sidecar, "run", **other_kind)
    await _refused("kind_not_supported", sidecar, "run", **{**fresh, "kind": "pg_basebackup"})
    outside = location.replace(sidecar.root.path, str(tmp_path / "elsewhere"))
    await _refused("bad_request", sidecar, "run", **{**fresh, "location": outside})
    backup_id, existing, _ = await sidecar.finished()
    await _refused("location_mismatch", sidecar, "run", **{**fresh, "backup_id": backup_id})
    await _refused("location_mismatch", sidecar, "run", **{**fresh, "location": existing})


async def test_restore_is_validated_and_answered_restore_not_available(
    tmp_path: Path, sock: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    backup_id, location, digest = await sidecar.finished()
    args = {"job_id": str(uuid.uuid4()), "backup_id": backup_id, "location": location,
            "digest": digest}  # fmt: skip
    await _refused("restore_not_available", sidecar, "restore", **args)


# -- verify ----------------------------------------------------------------------------------


async def test_verify_hashes_and_checks_one_descriptor_and_records_it(
    tmp_path: Path, sock: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    backup_id, location, digest = await sidecar.finished()
    result = await sidecar.handle("verify", backup_id=backup_id, location=location)
    assert result == {"method": "checksum", "checksum_sha256": digest}
    checked = _entries(sidecar)[-1]
    assert (checked["e"], checked["outcome"], checked["digest"]) == ("checked", "ok", digest)


async def test_verify_digest_is_of_the_descriptor_opened_not_a_file_swapped_in(
    tmp_path: Path, sock: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    backup_id, location, digest = await sidecar.finished()
    real = Root.open_artefact

    def open_then_swap(root: Root, where: str) -> tuple[int, int]:
        opened = real(root, where)
        swap = Path(where + ".swap")
        swap.write_bytes(age_bytes(seed=99))
        os.replace(swap, where)  # a different file now has the name
        return opened

    monkeypatch.setattr(Root, "open_artefact", open_then_swap)
    result = await sidecar.handle("verify", backup_id=backup_id, location=location)
    assert result["checksum_sha256"] == digest


_MALFORMED = {
    "two-stanzas": age_bytes(stanzas=("X25519", "X25519")),
    "other-type": age_bytes(stanzas=("ssh-ed25519",)),
    "over-4kib": age_bytes(pad=4096),
}


@pytest.mark.parametrize("case", [*_MALFORMED, "bytes-changed", "deleted", "symlink"])
async def test_verify_a_bad_artefact_is_refused_and_its_outcome_recorded(
    tmp_path: Path, sock: str, case: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    backup_id, location, _ = await sidecar.finished(content=_MALFORMED.get(case))
    code = "header_malformed" if case in _MALFORMED else "artefact_missing"
    if case == "bytes-changed":  # changed since the run
        code, data = "digest_mismatch", read(location)
        write(location, data[:-1] + bytes([data[-1] ^ 1]))
    elif case in ("deleted", "symlink"):
        os.replace(location, tmp_path / "moved.age")
        if case == "symlink":
            os.symlink(tmp_path / "moved.age", location)
    await _refused(code, sidecar, "verify", backup_id=backup_id, location=location)
    assert _entries(sidecar)[-1]["outcome"] == code


async def test_verify_only_the_location_its_record_holds(tmp_path: Path, sock: str) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    backup_id, location, _ = await sidecar.finished()
    _, other, _ = await sidecar.finished()
    await _refused("location_mismatch", sidecar, "verify", backup_id=backup_id, location=other)
    unknown = str(uuid.uuid4())
    await _refused("unknown_backup", sidecar, "verify", backup_id=unknown, location=location)


async def test_verify_one_at_a_time_is_busy(tmp_path: Path, sock: str) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    backup_id, location, _ = await sidecar.finished()
    async with sidecar.ops._verifying:
        await _refused("busy", sidecar, "verify", backup_id=backup_id, location=location)


async def test_plan_verify_and_remove_with_an_unreadable_record_are_ledger_unreadable(
    tmp_path: Path, sock: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    backup_id, location, _ = await sidecar.finished()
    write(Path(sidecar.root.path, LEDGER_DIR, FILE), b'{"torn":', append=True)
    await sidecar.ledger.load()
    args = {"kind": "pg_dump", "backup_id": backup_id, "location": location}
    for op in ("plan", "verify", "remove"):
        await _refused("ledger_unreadable", sidecar, op, **args)
    assert exists(location)


# -- remove and the floor ----------------------------------------------------------------------


async def test_remove_renames_to_quarantine_at_once_and_keeps_bytes(
    tmp_path: Path, sock: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    older, location, _ = await sidecar.finished()
    await sidecar.finished()
    data = read(location)
    result = await sidecar.handle("remove", backup_id=older, location=location)
    assert result == {"state": "quarantined", "purge_after": timestamp(T0 + timedelta(days=7))}
    kept = Path(sidecar.root.path, QUARANTINE_DIR, f"{older}.age")
    assert not exists(location) and read(kept) == data
    assert mode(kept) == 0o600
    again = await sidecar.handle("remove", backup_id=older, location=location)
    assert again == {"state": "already_removed", "purge_after": result["purge_after"]}


async def test_floor_remove_newest_finished_of_kind_is_refused_newest_artefact(
    tmp_path: Path, sock: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    only, location, _ = await sidecar.finished("config_bundle")
    await _refused("newest_artefact", sidecar, "remove", backup_id=only, location=location)
    assert exists(location)


async def test_floor_newest_is_judged_from_ledger_order_not_request_or_covers(
    tmp_path: Path, sock: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    older, older_at, _ = await sidecar.finished(covers_to=T0 + timedelta(days=1))
    newest, newest_at, _ = await sidecar.finished(covers_to=T0)  # finished later, covers less
    await _refused("newest_artefact", sidecar, "remove", backup_id=newest, location=newest_at)
    removed = await sidecar.handle("remove", backup_id=older, location=older_at)
    assert removed["state"] == "quarantined"


async def test_remove_location_not_in_ledger_is_location_mismatch(
    tmp_path: Path, sock: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    older, _, _ = await sidecar.finished()
    _, newest_at, _ = await sidecar.finished()
    await _refused("location_mismatch", sidecar, "remove", backup_id=older, location=newest_at)
    assert exists(newest_at)


async def test_remove_of_a_file_already_gone_is_already_removed_and_recorded(
    tmp_path: Path, sock: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    older, location, _ = await sidecar.finished()
    await sidecar.finished()
    os.unlink(location)
    result = await sidecar.handle("remove", backup_id=older, location=location)
    assert result == {"state": "already_removed", "purge_after": timestamp(T0)}
    assert _entries(sidecar)[-1]["e"] == "purged"


async def test_remove_purges_only_after_grace_period(tmp_path: Path, sock: str) -> None:
    sidecar = await _sidecar(tmp_path, sock, grace=timedelta(hours=2))
    older, location, _ = await sidecar.finished()
    await sidecar.finished()
    await sidecar.handle("remove", backup_id=older, location=location)
    kept = Path(sidecar.root.path, QUARANTINE_DIR, f"{older}.age")
    sidecar.clock.advance(hours=2, microseconds=-1)
    assert await sidecar.ops.sweep() == 0 and exists(kept)
    sidecar.clock.advance(microseconds=1)
    assert await sidecar.ops.sweep() == 1 and not exists(kept)
    assert _entries(sidecar)[-1]["e"] == "purged"
    assert await sidecar.ops.sweep() == 0
    again = await sidecar.handle("remove", backup_id=older, location=location)
    assert again["state"] == "already_removed"


async def test_a_cancelled_removal_still_lands_whole(tmp_path: Path, sock: str) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    older, location, _ = await sidecar.finished()
    await sidecar.finished()
    removing = asyncio.ensure_future(sidecar.handle("remove", backup_id=older, location=location))
    await asyncio.sleep(0)  # started: it holds the lock and is renaming in a worker thread
    removing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await removing
    while tasks.running():  # the removal, and its entry, run on to their end
        await asyncio.wait(tasks.running())
    assert sidecar.ledger.get(older).state == "quarantined"
    assert not exists(location)


async def test_a_ledger_replays_after_a_restart_with_every_state(tmp_path: Path, sock: str) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    older, location, _ = await sidecar.finished()
    newest, _, _ = await sidecar.finished()
    await sidecar.handle("remove", backup_id=older, location=location)
    restarted = Ledger(sidecar.root, sidecar.clock)
    await restarted.load()
    assert restarted.readable and restarted.get(older).state == "quarantined"
    assert restarted.newest("pg_dump") == newest
    restarted.close()


async def test_remove_at_the_task_bound_is_busy_before_the_rename_or_lands_whole(
    tmp_path: Path, sock: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidecar = await _sidecar(tmp_path, sock)
    older, location, _ = await sidecar.finished()
    await sidecar.finished()
    args = {"backup_id": older, "location": location}
    monkeypatch.setattr(tasks, "MAX_TASKS", len(tasks.running()))
    await _refused("busy", sidecar, "remove", **args)
    assert exists(location)
    monkeypatch.setattr(tasks, "MAX_TASKS", len(tasks.running()) + 1)  # the removal's own task
    assert (await sidecar.handle("remove", **args))["state"] == "quarantined"
    assert sidecar.ledger.get(older).state == "quarantined" and not exists(location)


async def test_floor_sweep_counts_a_purge_the_volume_refuses_and_goes_on(
    tmp_path: Path, sock: str
) -> None:
    sidecar = await _sidecar(tmp_path, sock, grace=timedelta(hours=1))
    removed = [await sidecar.finished() for _ in range(3)][:2]
    for backup_id, location, _ in removed:
        await sidecar.handle("remove", backup_id=backup_id, location=location)
    kept = f"{sidecar.root.path}/{QUARANTINE_DIR}/{removed[0][0]}.age"
    os.unlink(kept)
    os.mkdir(kept)  # its unlink fails (EISDIR): `artefact_missing`
    sidecar.clock.advance(hours=1)
    assert await sidecar.ops.sweep() == 1 and sidecar.floor.failures == 1
    states = [sidecar.ledger.get(backup_id).state for backup_id, _, _ in removed]
    assert states == ["quarantined", "purged"]
