"""E43-T10 (#1238): the offline audit-chain check over fake read-only stores: the chain is the
in-memory `FakeAuditRepository` walked by the in-app `AuditQueryService`, the catalogue side three
values. No connection string is built here; no database, no network."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository

from candleviewer import audit_chain_verify as entry
from candleviewer.admin import audit_chain_verify as cli
from candleviewer.audit.checkpoint import run_checkpoint
from candleviewer.audit.hashing import ChainHasherBusy
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.repository import HASHED_FIELDS
from candleviewer.storage.errors import AuditEntryTooLarge
from candleviewer.storage.guarded_privileges import GUARDED_PRIVILEGES
from candleviewer.storage.repositories.audit_sqlalchemy import AuditReadFailed
from candleviewer.storage.repositories.break_glass_cli_sqlalchemy import (
    SqlAlchemyAuditVerifyDatabase,
)

Cap = pytest.CaptureFixture[str]
MP = pytest.MonkeyPatch


class _Stores(cli.SeededStores):
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


@pytest.mark.parametrize("table", cli.AUDIT_TABLES)
def test_expected_grants_hold_no_privilege_the_guard_table_pins_revoked(table: str) -> None:
    assert GUARDED_PRIVILEGES[table] == {"UPDATE", "DELETE", "TRUNCATE"}
    for expected in cli.EXPECTED_GRANTS.values():
        assert not expected & GUARDED_PRIVILEGES[table]


async def test_run_passes_an_intact_chain_with_its_checkpoint_file(
    tmp_path: Path, capsys: Cap
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


async def test_run_names_a_changed_entry_and_skips_the_file(capsys: Cap) -> None:
    repo = await _repo(5)
    repo.rows[2]["actor_label"] = "someone-else"
    status = await _run(_Stores(repo), data=b"", batch=2)
    out = capsys.readouterr().out
    assert status == cli.EXIT_FAIL
    assert "FAIL chain: first_bad_id=3 kind=entry_hash_mismatch" in out
    assert "chain: entries_checked=3, head id 5" in out
    assert "SKIP checkpoint-file" in out


async def test_run_names_a_dropped_entry(capsys: Cap) -> None:
    repo = await _repo(5)
    del repo.rows[1]
    assert await _run(_Stores(repo)) == cli.EXIT_FAIL
    assert "FAIL chain: first_bad_id=3 kind=prev_hash_mismatch" in capsys.readouterr().out


async def test_run_names_a_reordered_entry(capsys: Cap) -> None:
    repo = await _repo(5)
    second, third = repo.rows[1], repo.rows[2]
    second["id"], third["id"] = third["id"], second["id"]
    assert await _run(_Stores(repo)) == cli.EXIT_FAIL
    assert "FAIL chain: first_bad_id=2 kind=prev_hash_mismatch" in capsys.readouterr().out


async def test_run_names_a_forged_database_checkpoint(capsys: Cap) -> None:
    repo = await _repo(3)
    repo.checkpoints[3] = {"head_hash": "d" * 64}
    assert await _run(_Stores(repo)) == cli.EXIT_FAIL
    assert "FAIL chain: first_bad_id=3 kind=checkpoint_mismatch" in capsys.readouterr().out


async def test_run_names_a_database_checkpoint_above_the_head(capsys: Cap) -> None:
    repo = await _repo(3)
    repo.checkpoints[9] = {"head_hash": "d" * 64}
    assert await _run(_Stores(repo)) == cli.EXIT_FAIL
    assert "FAIL chain: first_bad_id=9 kind=tail_truncated" in capsys.readouterr().out


async def test_run_passes_an_empty_log(capsys: Cap) -> None:
    assert await _run(_Stores(FakeAuditRepository())) == cli.EXIT_PASS
    assert "PASS chain (entries_checked=0, head id 0)" in capsys.readouterr().out


async def test_a_stop_mid_walk_reports_the_entries_already_checked(capsys: Cap) -> None:
    class _Drops(FakeAuditRepository):
        async def fetch_verify_batch(self, **kw: Any) -> list[tuple[Any, ...]]:
            if self.verify_calls:
                self.verify_calls.append((0, 0, 0))
                raise AuditReadFailed("57014")
            return await super().fetch_verify_batch(**kw)

    repo = _Drops()
    for row in (await _repo(5)).rows:
        repo.rows.append(row)
    assert await _run(_Stores(repo), batch=2) == cli.EXIT_STOPPED
    out = capsys.readouterr().out
    assert "STOPPED: store_unavailable sqlstate=57014 (entries_checked=2)" in out


async def test_check_only_reads_the_definitions_and_walks_nothing(capsys: Cap) -> None:
    repo = await _repo(3)
    repo.rows[1]["actor_label"] = "someone-else"
    assert await _run(_Stores(repo), check_only=True) == cli.EXIT_PASS
    assert repo.verify_calls == []
    assert "chain" not in capsys.readouterr().out


async def test_check_only_never_passes_a_checkpoint_file_silently(capsys: Cap) -> None:
    assert await _run(_Stores(await _repo(1)), check_only=True, data=b"{}\n") == cli.EXIT_PASS
    assert "SKIP checkpoint-file" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("line", "kind", "bad_id"),
    [
        ('{"head_id": 4, "head_hash": "' + "e" * 64 + '"}', "checkpoint_mismatch", 4),
        ('{"head_id": 2, "head_hash": "' + "e" * 64 + '"}', "checkpoint_missing", 2),
        ('{"head_id": 9, "head_hash": "' + "e" * 64 + '"}', "tail_truncated", 9),
    ],
)
async def test_file_heads_are_named_with_the_checkpoint_kinds(
    capsys: Cap, line: str, kind: str, bad_id: int
) -> None:
    repo = await _repo(3, gap_at=2)  # ids 1, 3, 4
    assert await _run(_Stores(repo), data=line.encode() + b"\n") == cli.EXIT_FAIL
    out = capsys.readouterr().out
    assert f"FAIL checkpoint-file: first_bad_id={bad_id} kind={kind}" in out
    assert ("chain absent)" in out) is (kind != "checkpoint_mismatch") and "None" not in out


async def test_a_file_head_above_the_walk_with_its_own_hash_is_a_later_append(capsys: Cap) -> None:
    repo = await _repo(3)
    head_hash = repo.rows[-1]["entry_hash"]
    findings = await cli.compare_heads(repo, [cli.FileHead(3, head_hash)], head_id=2)
    assert findings == []


async def test_file_lines_that_are_not_heads_are_findings_and_the_digest_is_checked(
    capsys: Cap,
) -> None:
    repo = await _repo(2)
    data = b'not json\n{"head_id": 0, "head_hash": "x"}\n\n[1]\n'
    assert await _run(_Stores(repo), data=data, sha256="0" * 64) == cli.EXIT_FAIL
    out = capsys.readouterr().out
    for number in (1, 2, 4):
        assert f"FAIL checkpoint-file: line {number}: not a checkpoint head" in out
    assert f"sha256 {hashlib.sha256(data).hexdigest()} != {'0' * 64}" in out


@pytest.mark.parametrize(
    "record",
    [
        {"head_id": 2**63, "head_hash": "e" * 64},
        {"head_id": 10**20, "head_hash": "e" * 64},
        {"head_id": 1, "head_hash": "E" * 64},
        {"head_id": 1, "head_hash": "g" * 64},
        {"head_id": 1, "head_hash": "e" * 63},
        {"head_id": True, "head_hash": "e" * 64},
    ],
)
def test_a_head_out_of_range_or_not_a_hash_is_a_line_finding(record: dict[str, Any]) -> None:
    heads, problems = cli.parse_heads(json.dumps(record).encode() + b"\n")
    assert heads == []
    assert problems == [cli.Finding("checkpoint-file", "line 1: not a checkpoint head")]


def test_the_greatest_bigint_head_id_is_a_head() -> None:
    heads, problems = cli.parse_heads(
        json.dumps({"head_id": 2**63 - 1, "head_hash": "e" * 64}).encode()
    )
    assert heads == [cli.FileHead(2**63 - 1, "e" * 64)] and problems == []


@pytest.mark.parametrize("data", [b"", b"\n\n"])
async def test_a_file_that_names_no_head_is_never_a_pass(capsys: Cap, data: bytes) -> None:
    sha256 = hashlib.sha256(data).hexdigest()
    assert await _run(_Stores(await _repo(2)), data=data, sha256=sha256) == cli.EXIT_FAIL
    out = capsys.readouterr().out
    assert "FAIL checkpoint-file: no checkpoint head in the file" in out
    assert "PASS checkpoint-file" not in out


async def test_run_names_a_widened_grant_a_missing_role_and_a_disabled_guard(capsys: Cap) -> None:
    stores = _Stores(await _repo(2))
    stores.held[("cv_app", "audit_log")] = frozenset({"SELECT", "INSERT", "TRIGGER"})
    del stores.held[("cv_ro", "audit_checkpoints")]
    append = ("trg_audit_append", "audit_log")
    stores.present[append] = (False, stores.present[append][1])
    del stores.present[("trg_audit_chain", "audit_log")]
    stores.present[("trg_audit_chain", "audit_checkpoints")] = (True, "")  # same name, other table
    assert await _run(stores) == cli.EXIT_FAIL
    out = capsys.readouterr().out
    assert "FAIL grants: cv_app on audit_log: extra ['TRIGGER'], missing []" in out
    assert "FAIL grants: cv_ro on audit_checkpoints: role or table missing" in out
    assert "FAIL triggers: trg_audit_append on audit_log: disabled" in out
    assert "FAIL triggers: trg_audit_chain on audit_log: absent" in out


async def test_the_deployed_field_order_must_be_hashed_fields(capsys: Cap) -> None:
    stores = _Stores(await _repo(1))
    stores.definition = stores.definition.replace("NEW.actor_label", "NEW.actor_ip", 1)
    assert await _run(stores, check_only=True) == cli.EXIT_FAIL
    assert "FAIL fields:" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("shape", "finding"),
    [
        ("type=23 function=public.forbid_mutation", "type=23"),  # UPDATE only, no DELETE
        ("type=26 function=public.forbid_mutation", "type=26"),  # a statement trigger
        ("type=25 function=public.forbid_mutation", "type=25"),  # AFTER
        ("type=27 function=public.audit_chain", "function=public.audit_chain"),
        ("type=27 function=other.forbid_mutation", "function=other.forbid_mutation"),
        ("type=27 function=public.forbid_mutation when", "when"),
        ("type=27 function=public.forbid_mutation columns", "columns"),
    ],
)
def test_a_guard_trigger_of_another_shape_is_a_finding(shape: str, finding: str) -> None:
    present = _present()
    present[("trg_audit_append", "audit_log")] = (True, shape)
    (only,) = cli.check_triggers(present, [])
    assert only.detail.startswith(f"trg_audit_append on audit_log: {shape}, expected type=27")
    assert finding in only.detail


def _present() -> dict[tuple[str, str], tuple[bool, str]]:
    return {(n, t): (True, shape) for n, (t, shape) in cli.EXPECTED_TRIGGERS.items()}


def test_a_trigger_reported_in_any_state_but_true_does_not_fire() -> None:
    present = _present()
    assert cli.check_triggers(present, [("session", "origin")]) == []
    chain = ("trg_audit_chain", "audit_log")
    for state in (False, None, 1, "O"):
        present[chain] = (state, present[chain][1])  # type: ignore[assignment]  # a store that returns a non-bool
        (only,) = cli.check_triggers(present, [])
        assert only.detail == "trg_audit_chain on audit_log: disabled"


@pytest.mark.parametrize("value", ["replica", "local", "", "Replica"])
def test_triggers_fail_unless_every_replication_role_setting_is_origin(value: str) -> None:
    settings = [("session", "origin"), ("this database, role cv_app", value), ("x", " ORIGIN")]
    (only,) = cli.check_triggers(_present(), settings)
    assert only.detail == f"session_replication_role {value!r} (this database, role cv_app)"


def _shipped_bodies() -> list[str]:
    """0045's upgrade and downgrade `audit_chain()` bodies, as `pg_get_functiondef` renders a
    deployed one: the header rewritten, the body verbatim between `$function$` quotes."""
    versions = Path(entry.__file__).resolve().parent / "migrations" / "versions"
    text = (versions / "0045_audit_chain_hardening.py").read_text(encoding="utf-8")
    bodies = text.split("$BODY$")[1::2]
    assert len(bodies) == 2
    header = (
        "CREATE OR REPLACE FUNCTION public.audit_chain()\n RETURNS trigger\n LANGUAGE plpgsql\n"
    )
    pinned = " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
    return [
        f"{header}{pinned}AS $function${bodies[0]}$function$\n",
        f"{header}AS $function${bodies[1]}$function$\n",
    ]


@pytest.mark.parametrize("index", [0, 1])
def test_the_shipped_definitions_frame_exactly_the_hashed_fields(index: int) -> None:
    definition = _shipped_bodies()[index]
    assert cli.framed_fields(definition) == ("prev_hash", *HASHED_FIELDS)
    assert cli.check_fields(definition) == []


def test_the_self_test_rendering_frames_exactly_the_hashed_fields() -> None:
    assert cli.check_fields(cli.RENDERED_CHAIN) == []


_SHIPPED = _shipped_bodies()[0]
_LABEL = "audit_field(NEW.actor_label)"
_EVENT = "audit_field(to_char(NEW.event_ts AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.USOF'))"


@pytest.mark.parametrize(
    ("definition", "why"),
    [
        (None, "audit_chain() not found"),
        ("", "audit_chain() not found"),
        # a field added to the digest outside `audit_field`
        (_SHIPPED.replace(_EVENT, f"{_EVENT} || NEW.object_label"), "term 17"),
        (_SHIPPED.replace(_EVENT, f"{_EVENT} || coalesce(NEW.object_label, '')"), "term 17"),
        # a field framed through another wrapper or cast
        (_SHIPPED.replace(_LABEL, "audit_field(lower(NEW.actor_label))"), "term 3"),
        (_SHIPPED.replace(_LABEL, "audit_field(NEW.actor_label::varchar(8))"), "term 3"),
        (_SHIPPED.replace(_LABEL, "audit_field(left(NEW.actor_label, 4))"), "term 3"),
        (_SHIPPED.replace("'YYYY-MM-DD", "'YYYY-MM"), "term 16"),
        (_SHIPPED.replace(_EVENT, "audit_field(NEW.event_ts::text)"), "term 16"),
        # an unframed concatenation inside a term
        (_SHIPPED.replace(_LABEL, "audit_field(NEW.actor_label || NEW.reason)"), "term 3"),
        # a value reaching the digest through a variable or another assignment
        (_SHIPPED.replace(_LABEL, "audit_field(v_label)"), "term 3"),
        (
            _SHIPPED.replace("RETURN NEW;", "NEW.reason := 'x'; RETURN NEW;"),
            "NEW used outside",
        ),
        (
            _SHIPPED.replace(
                "NEW.prev_hash := COALESCE(", "NEW.prev_hash := md5(NEW.reason) || COALESCE("
            ),
            "NEW used outside",
        ),
        (
            _SHIPPED.replace(
                "RETURN NEW;", "PERFORM pg_notify('c', row_to_json(new)::text); RETURN NEW;"
            ),
            "NEW used outside",
        ),
        (_SHIPPED.replace("RETURN NEW;", "RETURN NEW; RETURN NEW;"), "NEW used outside"),
        # a second digest, a changed algorithm or encoding, a comment
        (_SHIPPED.replace("RETURN NEW;", "PERFORM digest('x', 'md5'); RETURN NEW;"), "digest"),
        (_SHIPPED.replace("'sha256'), 'hex')", "'md5'), 'hex')"), "the digest arguments"),
        (_SHIPPED.replace("'sha256'), 'hex')", "'sha256'), 'base64')"), "the digest encoding"),
        (_SHIPPED.replace(_LABEL, f"{_LABEL} -- || audit_field(NEW.reason)"), "a comment"),
        (_SHIPPED.replace(_LABEL, f"/* x */ {_LABEL}"), "a comment"),
        (
            _SHIPPED.replace("NEW.entry_hash := encode(", "NEW.entry_hash := upper(encode("),
            "entry_hash",
        ),
        (_SHIPPED.replace(_LABEL, "audit_field(NEW.actor_label, 'x'"), "the digest arguments"),
        (_SHIPPED[: _SHIPPED.index("'sha256'")], "an unclosed call"),
        (_SHIPPED.replace("NEW.prev_hash := COALESCE", "last_hash := COALESCE"), "it sets"),
        (_SHIPPED.replace("RETURN NEW;", "NEW.id := 1; RETURN NEW;"), "it sets"),
        (_SHIPPED.replace(_LABEL, "audit_field('it''s"), "unterminated"),
        (_SHIPPED.replace(_LABEL, "audit_field(NEW.actor_label))"), "the digest"),
    ],
)
def test_a_definition_the_reader_does_not_know_is_never_a_pass(
    definition: str | None, why: str
) -> None:
    (finding,) = cli.check_fields(definition)
    assert finding.section == "fields" and why in finding.detail


@pytest.mark.parametrize(
    ("definition", "why"),
    [
        (_SHIPPED.replace(_LABEL, "audit_field(NEW.actor_ip)", 1), "16 framed"),
        (_SHIPPED.replace(f" || {_LABEL}", ""), "15 framed"),
        (_SHIPPED.replace(_EVENT, f"{_EVENT} || audit_field(NEW.object_label)"), "17 framed"),
    ],
)
def test_a_framed_list_other_than_the_hashed_fields_is_a_finding(definition: str, why: str) -> None:
    (finding,) = cli.check_fields(definition)
    assert finding.detail.startswith(why)


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
    capsys: Cap, error: Exception, reason: str
) -> None:
    stores = _Stores(await _repo(1))
    stores.fail = error
    assert await _run(stores) == cli.EXIT_STOPPED
    out = capsys.readouterr().out
    assert f"STOPPED: {reason}" in out and "(entries_checked=0)" in out
    assert "audit-db" not in out and stores.disposed


async def test_a_stop_after_a_failed_check_keeps_the_failure(capsys: Cap) -> None:
    class _Down(_Stores):
        async def held_privileges(self, *args: Any) -> dict[tuple[str, str], frozenset[str]]:
            return {}

        async def chain_definition(self) -> str | None:
            raise AuditReadFailed("08006")

    stores = _Down(await _repo(1))
    assert await _run(stores) == cli.EXIT_FAIL
    out = capsys.readouterr().out
    assert "FAIL grants" in out and "STOPPED: store_unavailable sqlstate=08006" in out


async def test_a_walk_short_of_the_whole_chain_is_never_a_pass(
    monkeypatch: MP, capsys: Cap
) -> None:
    original = AuditQueryService.run_verify

    async def partial(self: Any, plan: Any, **kw: Any) -> Any:
        return (await original(self, plan, **kw)).model_copy(update={"full_chain": False})

    monkeypatch.setattr(AuditQueryService, "run_verify", partial)
    assert await _run(_Stores(await _repo(2))) == cli.EXIT_STOPPED
    assert "STOPPED: internal_error (RuntimeError)" in capsys.readouterr().out


async def test_a_stored_value_that_is_not_a_hash_is_not_printed() -> None:
    repo = await _repo(1)
    repo.rows[0]["entry_hash"] = "\x1b[2Jforged"
    (finding,) = await cli.compare_heads(repo, [cli.FileHead(1, "e" * 64)], head_id=1)
    assert finding.detail.endswith("chain not a hash)") and "\x1b" not in finding.detail


async def test_the_whole_run_is_bounded_by_its_timeout(capsys: Cap) -> None:
    class _Slow(_Stores):
        async def chain_definition(self) -> str | None:
            await asyncio.sleep(60)
            return None

    assert await _run(_Slow(await _repo(1)), timeout_s=0.01) == cli.EXIT_STOPPED
    assert "STOPPED: timeout" in capsys.readouterr().out


async def test_a_dispose_failure_does_not_change_the_result(capsys: Cap) -> None:
    class _Sticky(_Stores):
        async def dispose(self) -> None:
            raise OSError("socket to audit-db.invalid")

    assert await _run(_Sticky(await _repo(1))) == cli.EXIT_PASS
    err = capsys.readouterr().err
    assert "pool not released (OSError)" in err and "audit-db" not in err


def test_main_self_test_passes(capsys: Cap) -> None:
    assert entry.main(["--self-test"]) == cli.EXIT_PASS
    assert "SELF-TEST: PASS (0 FAIL)" in capsys.readouterr().out


def test_main_without_a_login_refuses_and_never_uses_the_app_dsn(
    monkeypatch: MP, capsys: Cap
) -> None:
    monkeypatch.delenv("CV_AUDIT_VERIFY_DSN", raising=False)
    monkeypatch.setenv("CV_PG_DSN", "postgresql+asyncpg://app@app-db.invalid/candleviewer")
    assert entry.main([]) == cli.EXIT_USAGE
    assert "set CV_AUDIT_VERIFY_DSN" in capsys.readouterr().err


def test_main_builds_the_read_only_stores_from_the_settings_and_never_prints_them(
    monkeypatch: MP, capsys: Cap
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


def test_main_invalid_settings_name_only_the_class(monkeypatch: MP, capsys: Cap) -> None:
    monkeypatch.setenv("CV_AUDIT_VERIFY_STATEMENT_TIMEOUT_MS", "not-a-number-audit-db.invalid")
    assert entry.main([]) == cli.EXIT_USAGE
    err = capsys.readouterr().err
    assert "invalid settings (ValidationError)" in err and "audit-db" not in err


@pytest.mark.parametrize(
    ("argv", "why"),
    [
        (["--checkpoint-sha256", "ABC"], "--checkpoint-sha256 must be 64"),
        (["--timeout", "0"], "--timeout must be 1 to 21600 s"),
        (["--timeout", "1e-9"], "--timeout must be 1 to 21600 s"),
        (["--timeout", "nan"], "--timeout must be 1 to 21600 s"),
        (["--timeout", "21601"], "--timeout must be 1 to 21600 s"),
        (["--check", "--checkpoint-file", "x"], "--check walks no chain"),
        (["--self-test", "--checkpoint-file", "x"], "--self-test takes no other option"),
        (["--self-test", "--batch", "2000"], "--self-test takes no other option"),
        (["--self-test", "--timeout", "60"], "--self-test takes no other option"),
        (["--self-test", "--checkpoint-sha256", "0" * 64], "--self-test takes no other option"),
        (["--checkpoint-sha256", "0" * 64], "--checkpoint-sha256 needs --checkpoint-file"),
    ],
)
def test_main_refuses_bad_arguments_before_any_connection(
    capsys: Cap, argv: list[str], why: str
) -> None:
    def connect() -> None:
        raise AssertionError("no connection may be built")

    assert cli.main(argv, connect=connect) == cli.EXIT_USAGE
    assert why in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "10001", "x", "1.5"])
def test_a_bad_batch_names_the_range_not_every_choice(capsys: Cap, value: str) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--batch", value], connect=_never)
    assert raised.value.code == cli.EXIT_USAGE
    err = capsys.readouterr().err
    assert "argument --batch: must be an integer in 1..10000" in err and "9999" not in err


def test_main_uses_the_defaults_and_the_bounds_are_accepted(monkeypatch: MP) -> None:
    seen: list[Any] = []

    async def fake_run(stores: Any, *args: Any) -> int:
        seen.append(args)
        return cli.EXIT_PASS

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main([], connect=lambda: cli.SeededStores()) == cli.EXIT_PASS
    assert cli.main(["--batch", "1", "--timeout", "1"], connect=cli.SeededStores) == 0
    assert cli.main(["--batch", "10000", "--timeout", "21600"], connect=cli.SeededStores) == 0
    assert seen == [
        (False, None, None, cli.DEFAULT_BATCH, cli.DEFAULT_TIMEOUT_S),
        (False, None, None, 1, 1.0),
        (False, None, None, 10_000, 21_600.0),
    ]


def test_main_refuses_an_unreadable_or_oversized_file(
    tmp_path: Path, monkeypatch: MP, capsys: Cap
) -> None:
    assert cli.main(["--checkpoint-file", str(tmp_path / "absent")], connect=_never) == 2
    assert "unreadable (FileNotFoundError)" in capsys.readouterr().err
    big = tmp_path / "big.jsonl"
    big.write_bytes(b"x" * 11)
    monkeypatch.setattr(cli, "FILE_MAX_BYTES", 10)
    assert cli.main(["--checkpoint-file", str(big)], connect=_never) == 2
    assert "over 10 bytes" in capsys.readouterr().err


def test_main_hands_the_file_to_the_run(tmp_path: Path, monkeypatch: MP) -> None:
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
