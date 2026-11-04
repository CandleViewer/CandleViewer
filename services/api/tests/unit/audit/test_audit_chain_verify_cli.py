"""E43-T10: `python -m candleviewer.admin.audit_chain_verify` over a fake read-only reader.

The reader's chain side is the in-memory `FakeAuditRepository` (the `audit_chain()` emulation),
its catalogue side two dictionaries. The connection string is a fake one and never printed. No
database, no network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from audit_fakes import FakeAuditRepository

from candleviewer.admin import audit_chain_verify as cli
from candleviewer.audit import offline_verify as ov
from candleviewer.audit.checkpoint import run_checkpoint
from candleviewer.storage.repositories.audit_sqlalchemy import AuditReadFailed

FAKE_DSN = "postgresql+asyncpg://verifier@audit-db.invalid/candleviewer"


class _Reader:
    def __init__(self, repo: FakeAuditRepository) -> None:
        self.audit = repo
        self.grants: dict[tuple[str, str], frozenset[str]] = dict(ov.EXPECTED_GRANTS)
        self.guards = {name: (table, True) for name, table in ov.EXPECTED_TRIGGERS.items()}
        self.closed = False
        self.fail: Exception | None = None

    async def held_privileges(
        self, roles: list[str], tables: list[str], privileges: list[str]
    ) -> dict[tuple[str, str], frozenset[str]]:
        assert set(privileges) == set(ov.TABLE_PRIVILEGES)
        if self.fail is not None:
            raise self.fail
        return {k: v for k, v in self.grants.items() if k[0] in roles and k[1] in tables}

    async def triggers(self, tables: list[str]) -> dict[str, tuple[str, bool]]:
        return dict(self.guards)

    async def close(self) -> None:
        self.closed = True


async def _repo(count: int) -> FakeAuditRepository:
    repo = FakeAuditRepository()
    for n in range(count):
        await repo.insert(
            {
                "record_id": f"00000000-0000-4000-8000-{n:012d}",
                "actor_label": f"seed-{n}",
                "action": "audit.seed.entry",
                "outcome": "success",
                "severity": "info",
                "after_state": {"n": n},
                "event_ts": "2026-11-04T00:00:00.000001+00:00",
            }
        )
    return repo


async def _run(reader: _Reader, **kw: Any) -> int:
    return await cli.run(cast(Any, reader), **kw)


async def test_run_passes_an_intact_chain_with_its_mirror(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = await _repo(7)
    mirror = tmp_path / "audit-heads.jsonl"
    await run_checkpoint(repo, off_box_path=str(mirror))
    data = mirror.read_bytes()
    reader = _Reader(repo)
    status = await _run(reader, mirror=data, mirror_sha256=ov.mirror_digest(data), batch=3)
    out = capsys.readouterr().out
    assert status == cli.EXIT_PASS and reader.closed
    for section in ("grants", "triggers", "chain", "checkpoints", "mirror"):
        assert f"PASS {section}" in out
    assert "RESULT: PASS (0 FAIL)" in out
    assert [c[2] for c in repo.verify_calls] == [3, 3, 3]


async def test_run_names_a_changed_entry_and_skips_the_head_comparison(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = await _repo(5)
    repo.rows[2]["actor_label"] = "someone-else"
    status = await _run(_Reader(repo), batch=2)
    out = capsys.readouterr().out
    assert status == cli.EXIT_FAIL
    assert "FAIL chain_entry_hash_mismatch: chain breaks at id 3" in out
    assert "checkpoints" not in out


async def test_run_names_a_dropped_entry(capsys: pytest.CaptureFixture[str]) -> None:
    repo = await _repo(5)
    del repo.rows[1]
    assert await _run(_Reader(repo)) == cli.EXIT_FAIL
    assert "FAIL chain_prev_hash_mismatch: chain breaks at id 3" in capsys.readouterr().out


async def test_run_names_a_mirror_divergence_and_a_digest_mismatch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = await _repo(4)
    mirror = b'{"head_id": 4, "head_hash": "' + b"e" * 64 + b'"}\n'
    status = await _run(_Reader(repo), mirror=mirror, mirror_sha256="0" * 64)
    out = capsys.readouterr().out
    assert status == cli.EXIT_FAIL
    assert "FAIL mirror_divergence: id 4: mirror " + "e" * 64 in out
    assert "FAIL mirror_file_digest" in out


async def test_run_names_a_forged_database_checkpoint(capsys: pytest.CaptureFixture[str]) -> None:
    repo = await _repo(3)
    repo.checkpoints[2] = {"head_hash": repo.rows[1]["entry_hash"]}
    repo.checkpoints[3] = {"head_hash": "d" * 64}
    assert await _run(_Reader(repo)) == cli.EXIT_FAIL
    assert "FAIL checkpoint_divergence: id 3" in capsys.readouterr().out


async def test_run_names_a_checkpoint_above_the_local_head(
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = await _repo(3)
    repo.checkpoints[9] = {"head_hash": "d" * 64}
    assert await _run(_Reader(repo)) == cli.EXIT_FAIL
    out = capsys.readouterr().out
    assert (
        "FAIL checkpoint_ahead_of_local: checkpoint head id 9 is above the local head id 3" in out
    )


async def test_run_names_a_widened_grant_and_a_disabled_guard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    reader = _Reader(await _repo(2))
    reader.grants[("cv_app", "audit_log")] = frozenset({"SELECT", "INSERT", "DELETE"})
    reader.guards["trg_audit_append"] = ("audit_log", False)
    assert await _run(reader) == cli.EXIT_FAIL
    out = capsys.readouterr().out
    assert "FAIL grant_mismatch: cv_app on audit_log: extra ['DELETE']" in out
    assert "FAIL trigger_disabled: trg_audit_append" in out


async def test_run_passes_an_empty_log(capsys: pytest.CaptureFixture[str]) -> None:
    assert await _run(_Reader(FakeAuditRepository())) == cli.EXIT_PASS
    assert "PASS chain (0 entries, head id 0)" in capsys.readouterr().out


async def test_run_read_failure_is_unchecked_and_names_only_the_sqlstate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    reader = _Reader(await _repo(1))
    reader.fail = AuditReadFailed("42501")
    assert await _run(reader) == cli.EXIT_UNCHECKED
    err = capsys.readouterr().err
    assert "AuditReadFailed, sqlstate 42501" in err and reader.closed


async def test_run_connection_error_names_only_its_class(
    capsys: pytest.CaptureFixture[str],
) -> None:
    reader = _Reader(await _repo(1))
    reader.fail = ConnectionRefusedError("connect to audit-db.invalid:5432 refused")
    assert await _run(reader) == cli.EXIT_UNCHECKED
    err = capsys.readouterr().err
    assert "ConnectionRefusedError" in err and "audit-db" not in err


async def test_run_timeout_is_unchecked(capsys: pytest.CaptureFixture[str]) -> None:
    reader = _Reader(await _repo(1))
    reader.fail = TimeoutError()
    assert await _run(reader) == cli.EXIT_UNCHECKED
    assert "timed out" in capsys.readouterr().err


def test_main_self_test_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--self-test"]) == cli.EXIT_PASS
    out = capsys.readouterr().out
    assert out.count("PASS self-test") == 10 and "RESULT: PASS (0 FAIL)" in out


def test_main_check_passes_against_the_shipped_migrations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--check"]) == cli.EXIT_PASS
    assert "PASS static" in capsys.readouterr().out


def test_main_without_a_connection_string_checks_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(cli.DSN_ENV, raising=False)
    assert cli.main([]) == cli.EXIT_UNCHECKED
    assert cli.DSN_ENV in capsys.readouterr().err


def test_main_refuses_a_malformed_digest(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--mirror-sha256", "XYZ"]) == cli.EXIT_UNCHECKED
    assert "--mirror-sha256" in capsys.readouterr().err


def test_main_unreadable_mirror_checks_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(cli.DSN_ENV, FAKE_DSN)
    argv = ["--mirror", str(tmp_path / "absent.jsonl")]
    assert cli.main(argv, open_reader=lambda _dsn: _Reader(FakeAuditRepository())) == 2
    assert "FileNotFoundError" in capsys.readouterr().err


def test_main_without_a_reader_runs_only_the_offline_modes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(cli.DSN_ENV, FAKE_DSN)
    assert cli.main([]) == cli.EXIT_UNCHECKED
    assert "audit-db" not in capsys.readouterr().err


def test_main_runs_the_reader_from_the_environment_and_never_prints_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []
    repo = FakeAuditRepository()

    def factory(dsn: str) -> _Reader:
        seen.append(dsn)
        return _Reader(repo)

    mirror = tmp_path / "heads.jsonl"
    mirror.write_bytes(b"")
    monkeypatch.setenv(cli.DSN_ENV, FAKE_DSN)
    assert cli.main(["--mirror", str(mirror), "--batch", "5"], open_reader=factory) == 0
    captured = capsys.readouterr()
    assert seen == [FAKE_DSN]
    assert "audit-db" not in captured.out + captured.err
    assert "PASS mirror (0 heads" in captured.out


def test_entry_point_hands_the_flow_the_postgres_reader(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from candleviewer import audit_chain_verify as entry
    from candleviewer.storage.repositories.audit_offline_sqlalchemy import (
        SqlAlchemyAuditOfflineReader,
    )

    handed: list[Any] = []
    monkeypatch.setattr(cli, "main", lambda argv, open_reader: handed.append(open_reader))
    entry.main(["--self-test"])
    assert handed == [SqlAlchemyAuditOfflineReader]
