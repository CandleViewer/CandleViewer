"""E43-T10 (#1238): the offline audit-chain check over fake read-only stores.

The chain side is the in-memory `FakeAuditRepository` (its own `audit_chain()` emulation), walked
by the in-app `AuditQueryService`; the catalogue side is three values. The connection string is
never built here. No database, no network.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository

from candleviewer import audit_chain_verify as entry
from candleviewer.admin import audit_chain_verify as cli
from candleviewer.audit.checkpoint import run_checkpoint
from candleviewer.audit.hashing import ChainHasherBusy
from candleviewer.audit.repository import HASHED_FIELDS
from candleviewer.storage.errors import AuditEntryTooLarge
from candleviewer.storage.guarded_privileges import GUARDED_PRIVILEGES
from candleviewer.storage.repositories.audit_sqlalchemy import AuditReadFailed
from candleviewer.storage.repositories.break_glass_cli_sqlalchemy import (
    SqlAlchemyAuditVerifyDatabase,
)


class _Stores(cli.SeededStores):
    """The seeded catalogue side over a `FakeAuditRepository` chain."""

    def __init__(self, repo: FakeAuditRepository) -> None:
        super().__init__(0)
        self.repo = repo
        self.fail: Exception | None = None

    @property
    def audit_log(self) -> Any:
        return self.repo

    async def held_privileges(
        self, roles: list[str], tables: list[str], privileges: list[str]
    ) -> dict[tuple[str, str], frozenset[str]]:
        assert (roles, tables) == (["cv_app", "cv_ro"], ["audit_log", "audit_checkpoints"])
        assert privileges == list(cli.TABLE_PRIVILEGES)
        if self.fail is not None:
            raise self.fail
        return dict(self.held)


async def _repo(count: int, *, gap_at: int | None = None) -> FakeAuditRepository:
    """`count` entries; with `gap_at`, no entry has that id (as a rolled-back insert leaves it)."""
    repo = FakeAuditRepository()
    for n in range(count):
        if n + 1 == gap_at:
            repo.burn_ids(1)
        await repo.insert(
            {
                "record_id": f"00000000-0000-4000-8000-{n:012d}",
                "actor_label": f"seed-{n}",
                "action": "audit.seed.entry",
                "outcome": "success",
                "severity": "info",
                "after_state": {"n": n, "label": "zé"},
                "event_ts": "2026-11-04T00:00:00.000001+00:00",
            }
        )
    return repo


async def _run(stores: _Stores, **kw: Any) -> int:
    return await cli.run(stores, **kw)


# --- the expected grant model is the pinned guard table's complement ---------------------------


@pytest.mark.parametrize("table", cli.AUDIT_TABLES)
def test_expected_grants_hold_no_privilege_the_guard_table_pins_revoked(table: str) -> None:
    assert GUARDED_PRIVILEGES[table] <= set(cli.TABLE_PRIVILEGES)
    for expected in cli.EXPECTED_GRANTS.values():
        assert not expected & GUARDED_PRIVILEGES[table]


# --- the chain: the in-app walk, reported in `audit_ack_break`'s vocabulary --------------------


async def test_run_passes_an_intact_chain_with_its_checkpoint_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = await _repo(7)
    path = tmp_path / "audit-heads.jsonl"
    await run_checkpoint(repo, off_box_path=str(path))
    data = path.read_bytes()
    stores = _Stores(repo)
    status = await _run(stores, data=data, sha256=hashlib.sha256(data).hexdigest(), batch=3)
    out = capsys.readouterr().out
    assert status == cli.EXIT_PASS and stores.disposed
    for section in ("grants", "triggers", "fields", "chain", "checkpoint-file"):
        assert f"PASS {section}" in out
    assert "PASS chain (entries_checked=7, head id 7)" in out
    assert "RESULT: PASS (0 FAIL)" in out
    assert [c[2] for c in repo.verify_calls] == [3, 3, 3]


async def test_run_names_a_changed_entry_and_skips_the_file(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = await _repo(5)
    repo.rows[2]["actor_label"] = "someone-else"
    status = await _run(_Stores(repo), data=b"", batch=2)
    out = capsys.readouterr().out
    assert status == cli.EXIT_FAIL
    assert "FAIL chain: first_bad_id=3 kind=entry_hash_mismatch" in out
    assert "chain: entries_checked=3, head id 5" in out
    assert "SKIP checkpoint-file" in out


async def test_run_names_a_dropped_entry(capsys: pytest.CaptureFixture[str]) -> None:
    repo = await _repo(5)
    del repo.rows[1]
    assert await _run(_Stores(repo)) == cli.EXIT_FAIL
    assert "FAIL chain: first_bad_id=3 kind=prev_hash_mismatch" in capsys.readouterr().out


async def test_run_names_a_forged_database_checkpoint(capsys: pytest.CaptureFixture[str]) -> None:
    repo = await _repo(3)
    repo.checkpoints[3] = {"head_hash": "d" * 64}
    assert await _run(_Stores(repo)) == cli.EXIT_FAIL
    assert "FAIL chain: first_bad_id=3 kind=checkpoint_mismatch" in capsys.readouterr().out


async def test_run_names_a_database_checkpoint_above_the_head(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = await _repo(3)
    repo.checkpoints[9] = {"head_hash": "d" * 64}
    assert await _run(_Stores(repo)) == cli.EXIT_FAIL
    assert "FAIL chain: first_bad_id=9 kind=tail_truncated" in capsys.readouterr().out


async def test_run_passes_an_empty_log(capsys: pytest.CaptureFixture[str]) -> None:
    assert await _run(_Stores(FakeAuditRepository())) == cli.EXIT_PASS
    assert "PASS chain (entries_checked=0, head id 0)" in capsys.readouterr().out


async def test_check_only_reads_the_definitions_and_walks_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = await _repo(3)
    repo.rows[1]["actor_label"] = "someone-else"
    assert await _run(_Stores(repo), check_only=True) == cli.EXIT_PASS
    assert repo.verify_calls == []
    assert "chain" not in capsys.readouterr().out


# --- the checkpoint file (interim anchor) ------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "kind", "bad_id"),
    [
        ('{"head_id": 4, "head_hash": "' + "e" * 64 + '"}', "checkpoint_mismatch", 4),
        ('{"head_id": 2, "head_hash": "' + "e" * 64 + '"}', "checkpoint_missing", 2),
        ('{"head_id": 9, "head_hash": "' + "e" * 64 + '"}', "tail_truncated", 9),
    ],
)
async def test_file_heads_are_named_with_the_checkpoint_kinds(
    capsys: pytest.CaptureFixture[str], line: str, kind: str, bad_id: int
) -> None:
    repo = await _repo(3, gap_at=2)  # ids 1, 3, 4
    assert await _run(_Stores(repo), data=line.encode() + b"\n") == cli.EXIT_FAIL
    assert f"FAIL checkpoint-file: first_bad_id={bad_id} kind={kind}" in capsys.readouterr().out


async def test_a_file_head_above_the_walk_with_its_own_hash_is_a_later_append(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = await _repo(3)
    head_hash = repo.rows[-1]["entry_hash"]
    findings = await cli.compare_heads(repo, [cli.FileHead(3, head_hash)], head_id=2)
    assert findings == []


async def test_file_lines_that_are_not_heads_are_findings_and_the_digest_is_checked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = await _repo(2)
    data = b'not json\n{"head_id": 0, "head_hash": "x"}\n\n[1]\n'
    assert await _run(_Stores(repo), data=data, sha256="0" * 64) == cli.EXIT_FAIL
    out = capsys.readouterr().out
    for number in (1, 2, 4):
        assert f"FAIL checkpoint-file: line {number}: not a checkpoint head" in out
    assert f"sha256 {hashlib.sha256(data).hexdigest()} != {'0' * 64}" in out


# --- the definitions ---------------------------------------------------------------------------


async def test_run_names_a_widened_grant_a_missing_role_and_a_disabled_guard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stores = _Stores(await _repo(2))
    stores.held[("cv_app", "audit_log")] = frozenset({"SELECT", "INSERT", "TRIGGER"})
    del stores.held[("cv_ro", "audit_checkpoints")]
    stores.present["trg_audit_append"] = ("audit_log", False)
    del stores.present["trg_audit_chain"]
    assert await _run(stores) == cli.EXIT_FAIL
    out = capsys.readouterr().out
    assert "FAIL grants: cv_app on audit_log: extra ['TRIGGER'], missing []" in out
    assert "FAIL grants: cv_ro on audit_checkpoints: role or table missing" in out
    assert "FAIL triggers: trg_audit_append on audit_log: disabled" in out
    assert "FAIL triggers: trg_audit_chain on audit_log: absent" in out


async def test_the_deployed_field_order_must_be_hashed_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stores = _Stores(await _repo(1))
    stores.definition = stores.definition.replace("NEW.actor_label", "NEW.actor_ip", 1)
    assert await _run(stores, check_only=True) == cli.EXIT_FAIL
    assert "FAIL fields:" in capsys.readouterr().out


def test_framed_fields_reads_the_shipped_definition() -> None:
    versions = Path(entry.__file__).resolve().parent / "migrations" / "versions"
    body = (versions / "0045_audit_chain_hardening.py").read_text(encoding="utf-8")
    assert cli.framed_fields(body)[:16] == ("prev_hash", *HASHED_FIELDS)


# --- stops: fail closed, own exit code, no driver text -----------------------------------------


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AuditReadFailed("42501"), "store_unavailable sqlstate=42501"),
        (TimeoutError(), "timeout"),
        (ChainHasherBusy(), "hasher_busy"),
        (AuditEntryTooLarge(5), "entry_too_large@5"),
        (ConnectionRefusedError("connect to audit-db.invalid refused"), "internal_error"),
    ],
)
async def test_a_stop_is_never_a_pass_and_names_no_driver_text(
    capsys: pytest.CaptureFixture[str], error: Exception, reason: str
) -> None:
    stores = _Stores(await _repo(1))
    stores.fail = error
    assert await _run(stores) == cli.EXIT_STOPPED
    out = capsys.readouterr().out
    assert f"STOPPED: {reason}" in out and "(entries_checked=0)" in out
    assert "audit-db" not in out and stores.disposed


async def test_the_whole_run_is_bounded_by_its_timeout(capsys: pytest.CaptureFixture[str]) -> None:
    class _Slow(_Stores):
        async def chain_definition(self) -> str | None:
            await asyncio.sleep(60)
            return None

    assert await _run(_Slow(await _repo(1)), timeout_s=0.01) == cli.EXIT_STOPPED
    assert "STOPPED: timeout" in capsys.readouterr().out


async def test_a_dispose_failure_does_not_change_the_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Sticky(_Stores):
        async def dispose(self) -> None:
            raise OSError("socket to audit-db.invalid")

    assert await _run(_Sticky(await _repo(1))) == cli.EXIT_PASS
    err = capsys.readouterr().err
    assert "pool not released (OSError)" in err and "audit-db" not in err


# --- the entry point ---------------------------------------------------------------------------


def test_main_self_test_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert entry.main(["--self-test"]) == cli.EXIT_PASS
    assert "SELF-TEST: PASS (0 FAIL)" in capsys.readouterr().out


def test_main_without_a_login_refuses_and_never_uses_the_app_dsn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CV_AUDIT_VERIFY_DSN", raising=False)
    monkeypatch.setenv("CV_PG_DSN", "postgresql+asyncpg://app@app-db.invalid/candleviewer")
    assert entry.main([]) == cli.EXIT_USAGE
    assert "set CV_AUDIT_VERIFY_DSN" in capsys.readouterr().err


def test_main_builds_the_read_only_stores_from_the_settings_and_never_prints_them(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CV_AUDIT_VERIFY_DSN", "postgresql+asyncpg://ro@audit-db.invalid/cv")
    monkeypatch.setenv("CV_AUDIT_VERIFY_STATEMENT_TIMEOUT_MS", "7000")
    built: list[SqlAlchemyAuditVerifyDatabase] = []

    async def fake_run(stores: Any, *args: Any) -> int:
        built.append(stores)
        await stores.dispose()
        return cli.EXIT_PASS

    monkeypatch.setattr(cli, "run", fake_run)
    assert entry.main(["--check"]) == cli.EXIT_PASS
    (stores,) = built
    assert isinstance(stores, SqlAlchemyAuditVerifyDatabase)
    assert stores._read_only and stores.application_name.startswith("candleviewer:audit-verify:")
    assert stores.audit_log._verify_timeout_ms == 7000
    captured = capsys.readouterr()
    assert "audit-db" not in captured.out + captured.err


def test_main_invalid_settings_name_only_the_class(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CV_AUDIT_VERIFY_STATEMENT_TIMEOUT_MS", "not-a-number-audit-db.invalid")
    assert entry.main([]) == cli.EXIT_USAGE
    err = capsys.readouterr().err
    assert "invalid settings (ValidationError)" in err and "audit-db" not in err


@pytest.mark.parametrize(
    ("argv", "why"),
    [
        (["--checkpoint-sha256", "ABC"], "--checkpoint-sha256 must be 64"),
        (["--timeout", "0"], "--timeout must be above 0"),
        (["--timeout", "21601"], "--timeout must be above 0"),
    ],
)
def test_main_refuses_bad_arguments_before_any_connection(
    capsys: pytest.CaptureFixture[str], argv: list[str], why: str
) -> None:
    def connect() -> None:
        raise AssertionError("no connection may be built")

    assert cli.main(argv, connect=connect) == cli.EXIT_USAGE
    assert why in capsys.readouterr().err


def test_main_refuses_an_unreadable_or_oversized_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--checkpoint-file", str(tmp_path / "absent")], connect=_never) == 2
    assert "unreadable (FileNotFoundError)" in capsys.readouterr().err
    big = tmp_path / "big.jsonl"
    big.write_bytes(b"x" * 11)
    monkeypatch.setattr(cli, "FILE_MAX_BYTES", 10)
    assert cli.main(["--checkpoint-file", str(big)], connect=_never) == 2
    assert "over 10 bytes" in capsys.readouterr().err


def test_main_hands_the_file_to_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "heads.jsonl"
    path.write_bytes(b"{}\n")
    seen: list[Any] = []

    async def fake_run(stores: Any, *args: Any) -> int:
        seen.extend(args)
        return cli.EXIT_FAIL

    monkeypatch.setattr(cli, "run", fake_run)
    argv = ["--checkpoint-file", str(path), "--batch", "50", "--timeout", "9"]
    assert cli.main(argv, connect=lambda: cli.SeededStores()) == cli.EXIT_FAIL
    assert seen == [False, b"{}\n", None, 50, 9.0]


def _never() -> None:
    raise AssertionError("no connection may be built")
