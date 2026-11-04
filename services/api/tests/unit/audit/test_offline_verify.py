"""E43-T10: offline audit-integrity checks on a seeded chain (`audit.offline_verify`).

A changed, a dropped and a re-ordered entry are each named at their id; the grant model is held to
the files that declare it (`0003_audit_log`'s REVOKE, `pg_bootstrap.sql`'s default privileges);
the off-box file the checkpoint job writes is compared head by head. No database, no network.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from audit_fakes import FakeAuditRepository
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.audit import offline_verify as ov
from candleviewer.audit.checkpoint import run_checkpoint
from candleviewer.audit.query import _canonical_digest

_API = Path(__file__).resolve().parents[3]
_VERSIONS = _API / "candleviewer" / "migrations" / "versions"
_BOOTSTRAP = _API.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"


def _swap_contents(rows: list[tuple[object, ...]], i: int, j: int) -> list[tuple[object, ...]]:
    """Two entries traded places: each id now carries the other's link, hash and fields."""
    out = list(rows)
    out[i], out[j] = (rows[i][0], *rows[j][1:]), (rows[j][0], *rows[i][1:])
    return out


def _break(walker: ov.ChainWalker) -> tuple[str, int] | None:
    found = walker.first_break
    if found is None:
        return None
    at = re.search(r"at id (\d+)", found.detail)
    assert at is not None
    return found.code, int(at.group(1))


# --- the chain ---------------------------------------------------------------------------------


def test_walk_seeded_chain_passes_to_its_head() -> None:
    rows = ov.seed_rows(12)
    walker = ov.walk(rows)
    assert _break(walker) is None
    assert walker.checked == 12
    assert (walker.head_id, walker.head_hash) == (rows[-1][0], rows[-1][2])


def test_walk_first_entry_links_to_genesis() -> None:
    rows = ov.seed_rows(1)
    assert rows[0][1] == ov.GENESIS == "0" * 64


def test_walk_matches_an_independent_sha256_of_the_framed_fields() -> None:
    """A golden check outside the shared encoder: `audit_field()` framing, by hand."""
    (row,) = ov.seed_rows(1)
    framed = "".join("-" if v is None else f"{len(str(v))}:{v}" for v in (ov.GENESIS, *row[3:]))
    assert hashlib.sha256(framed.encode("utf-8")).hexdigest() == row[2]


@pytest.mark.parametrize("field_index", range(15))
def test_walk_changed_entry_is_named_at_its_id(field_index: int) -> None:
    rows = ov.seed_rows(6)
    victim = list(rows[3])
    victim[3 + field_index] = "changed"
    rows[3] = tuple(victim)
    assert _break(ov.walk(rows)) == ("chain_entry_hash_mismatch", rows[3][0])


def test_walk_changed_entry_hash_is_named_at_its_id() -> None:
    rows = ov.seed_rows(6)
    rows[2] = (rows[2][0], rows[2][1], "a" * 64, *rows[2][3:])
    assert _break(ov.walk(rows)) == ("chain_entry_hash_mismatch", rows[2][0])


@pytest.mark.parametrize("dropped", [0, 3, 6])
def test_walk_dropped_entry_is_named_at_the_next_id(dropped: int) -> None:
    rows = ov.seed_rows(8)
    kept = rows[:dropped] + rows[dropped + 1 :]
    assert _break(ov.walk(kept)) == ("chain_prev_hash_mismatch", rows[dropped + 1][0])


def test_walk_dropped_tail_is_not_a_chain_break_but_the_mirror_names_it() -> None:
    rows = ov.seed_rows(8)
    head = ov.MirrorHead(int(str(rows[-1][0])), str(rows[-1][2]))
    walker = ov.walk(rows[:-1], watch=[head.head_id])
    assert _break(walker) is None
    assert [f.code for f in ov.compare_heads("mirror", [head], walker)] == ["mirror_ahead_of_local"]


def test_walk_reordered_contents_are_named_at_the_first_moved_id() -> None:
    rows = ov.seed_rows(8)
    assert _break(ov.walk(_swap_contents(rows, 2, 5))) == ("chain_prev_hash_mismatch", rows[2][0])


def test_walk_reordered_rows_break_at_the_first_out_of_place_row() -> None:
    rows = ov.seed_rows(8)
    moved = list(rows)
    moved[4], moved[5] = rows[5], rows[4]
    assert _break(ov.walk(moved)) == ("chain_prev_hash_mismatch", rows[5][0])


def test_walk_a_repeated_or_falling_id_is_an_id_order_break() -> None:
    rows = ov.seed_rows(5)
    assert _break(ov.walk([*rows, rows[2]])) == ("chain_id_order", rows[2][0])


def test_walk_short_row_is_a_shape_break() -> None:
    rows = ov.seed_rows(3)
    rows[1] = rows[1][:-1]
    assert _break(ov.walk(rows)) == ("chain_row_shape", rows[1][0])


def test_walk_stops_at_the_first_break_across_batches() -> None:
    rows = ov.seed_rows(10)
    rows[4] = (*rows[4][:5], "changed", *rows[4][6:])
    walker = ov.ChainWalker()
    assert walker.feed(rows[:3]) is True
    assert walker.feed(rows[3:7]) is False
    assert walker.feed(rows[7:]) is False
    assert walker.broken and walker.checked == 5


@given(st.lists(st.text(max_size=20), min_size=1, max_size=6))
def test_walk_any_unicode_rendering_verifies(labels: list[str]) -> None:
    """Encode then verify is stable for any text (code points counted as Postgres `length`)."""
    rows = ov.seed_rows(len(labels))
    reseeded: list[tuple[object, ...]] = []
    prev = ov.GENESIS
    for row, label in zip(rows, labels, strict=True):
        values = [label if i == 1 else v for i, v in enumerate(row[3:])]
        entry = _canonical_digest(prev, [None if v is None else str(v) for v in values])
        reseeded.append((row[0], prev, entry, *values))
        prev = entry
    assert _break(ov.walk(reseeded)) is None


# --- the mirror --------------------------------------------------------------------------------


async def _seeded_repository(count: int) -> FakeAuditRepository:
    repo = FakeAuditRepository()
    for n in range(count):
        await repo.insert(
            {
                "record_id": f"00000000-0000-4000-8000-{n:012d}",
                "actor_label": f"seed-{n}",
                "action": "audit.seed.entry",
                "outcome": "success",
                "severity": "info",
                "after_state": {"n": n, "note": "[REDACTED]"},
                "event_ts": "2026-11-04T00:00:00.000001+00:00",
            }
        )
        repo.burn_ids(1)
    return repo


async def _walk_repository(repo: FakeAuditRepository, watch: set[int]) -> ov.ChainWalker:
    head = await repo.read_head()
    assert head is not None
    rows = await repo.fetch_verify_batch(after_id=0, to_id=head[0], limit=1000)
    return ov.walk(rows, watch=watch)


async def test_mirror_written_by_the_checkpoint_job_matches_the_chain(tmp_path: Path) -> None:
    repo = await _seeded_repository(4)
    mirror = tmp_path / "off-box" / "audit-heads.jsonl"
    await run_checkpoint(repo, off_box_path=str(mirror))
    await repo.insert(
        {
            "record_id": "00000000-0000-4000-8000-999999999999",
            "actor_label": "late",
            "action": "audit.seed.entry",
            "outcome": "success",
            "severity": "info",
            "event_ts": "2026-11-04T00:00:01.000001+00:00",
        }
    )
    await run_checkpoint(repo, off_box_path=str(mirror))
    heads, problems = ov.parse_mirror(mirror.read_text(encoding="utf-8"))
    walker = await _walk_repository(repo, {h.head_id for h in heads})
    assert problems == [] and len(heads) == 2
    assert _break(walker) is None
    assert ov.compare_heads("mirror", heads, walker) == []


async def test_mirror_divergence_names_both_heads(tmp_path: Path) -> None:
    repo = await _seeded_repository(3)
    head = await repo.read_head()
    assert head is not None
    forged = ov.MirrorHead(head[0], "b" * 64)
    walker = await _walk_repository(repo, {head[0]})
    (finding,) = ov.compare_heads("mirror", [forged], walker)
    assert finding.code == "mirror_divergence"
    assert "b" * 64 in finding.detail and head[1] in finding.detail


def test_mirror_head_on_a_gap_id_is_missing() -> None:
    rows = ov.seed_rows(4)  # ids 2, 4, 6, 8
    walker = ov.walk(rows, watch=[5])
    (finding,) = ov.compare_heads("checkpoint", [ov.MirrorHead(5, "c" * 64)], walker)
    assert finding.code == "checkpoint_head_missing"


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        "[1, 2]",
        '{"head_id": true, "head_hash": "' + "a" * 64 + '"}',
        '{"head_id": 0, "head_hash": "' + "a" * 64 + '"}',
        '{"head_id": 3, "head_hash": "' + "A" * 64 + '"}',
        '{"head_id": 3}',
    ],
)
def test_parse_mirror_refuses_a_malformed_line(line: str) -> None:
    good = '{"head_id": 2, "head_hash": "' + "a" * 64 + '", "row_count": 1}'
    heads, problems = ov.parse_mirror(f"{good}\n\n{line}\n")
    assert heads == [ov.MirrorHead(2, "a" * 64)]
    assert problems == [ov.Finding("mirror_line_invalid", "line 3")]


def test_mirror_digest_is_the_sha256_of_the_bytes() -> None:
    data = b'{"head_id": 2}\n'
    assert ov.mirror_digest(data) == hashlib.sha256(data).hexdigest()


# --- the grant model ---------------------------------------------------------------------------


def test_expected_grants_are_the_bootstrap_defaults_less_the_0003_revokes() -> None:
    """The matrix the tool asserts is derived from the two files that declare it, not restated."""
    bootstrap = _BOOTSTRAP.read_text(encoding="utf-8")
    defaults = dict(
        (role, frozenset(p.strip() for p in privs.split(",")))
        for privs, role in re.findall(
            r"ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public\s+GRANT ([A-Z, ]+) "
            r"ON TABLES TO (\w+);",
            bootstrap,
        )
    )
    revokes = ov.declared_revokes((_VERSIONS / "0003_audit_log.py").read_text(encoding="utf-8"))
    derived = {
        (role, table): defaults[role] - revokes[(role, table)]
        for role in ov.APP_ROLES
        for table in ov.AUDIT_TABLES
    }
    assert derived == dict(ov.EXPECTED_GRANTS)
    assert all(revokes[pair] == ov.REVOKED for pair in ov.EXPECTED_GRANTS)


def test_check_grants_passes_the_declared_model() -> None:
    assert ov.check_grants(dict(ov.EXPECTED_GRANTS)) == []


@pytest.mark.parametrize("privilege", ["UPDATE", "DELETE", "TRUNCATE", "TRIGGER"])
def test_check_grants_names_a_widened_grant(privilege: str) -> None:
    held = dict(ov.EXPECTED_GRANTS)
    held[("cv_app", "audit_log")] = held[("cv_app", "audit_log")] | {privilege}
    (finding,) = ov.check_grants(held)
    assert finding.code == "grant_mismatch" and f"extra ['{privilege}']" in finding.detail


def test_check_grants_names_a_missing_grant_and_an_absent_role() -> None:
    held = dict(ov.EXPECTED_GRANTS)
    held[("cv_app", "audit_checkpoints")] = frozenset({"SELECT"})
    del held[("cv_ro", "audit_log")]
    codes = sorted(f.code for f in ov.check_grants(held))
    assert codes == ["grant_absent", "grant_mismatch"]


def test_check_triggers_names_absent_misplaced_and_disabled_guards() -> None:
    present = {name: (table, True) for name, table in ov.EXPECTED_TRIGGERS.items()}
    assert ov.check_triggers(present) == []
    present["trg_audit_append"] = ("audit_log", False)
    present["trg_audit_ckpt_append"] = ("audit_log", True)
    del present["trg_audit_no_truncate"]
    codes = sorted(f.code for f in ov.check_triggers(present))
    assert codes == ["trigger_absent", "trigger_absent", "trigger_disabled"]


# --- the static check against the migrations ---------------------------------------------------


def _latest_chain_sql() -> str:
    chain = ""
    pattern = re.compile(r"CREATE (?:OR REPLACE )?FUNCTION audit_chain\(\).*?\$BODY\$;", re.S)
    for path in sorted(_VERSIONS.glob("[0-9]*.py")):
        found = pattern.search(path.read_text(encoding="utf-8"))
        chain = found.group(0) if found else chain
    return chain


def test_static_findings_hold_for_the_shipped_migrations() -> None:
    audit_sql = (_VERSIONS / "0003_audit_log.py").read_text(encoding="utf-8")
    assert ov.static_findings(_latest_chain_sql(), audit_sql) == []


def test_static_findings_name_a_reordered_trigger_field() -> None:
    audit_sql = (_VERSIONS / "0003_audit_log.py").read_text(encoding="utf-8")
    chain = (
        _latest_chain_sql().replace("NEW.action)", "NEW.tmp)").replace("NEW.reason)", "NEW.action)")
    )
    codes = [f.code for f in ov.static_findings(chain, audit_sql)]
    assert codes == ["static_field_order"]


def test_static_findings_name_a_dropped_revoke_and_trigger() -> None:
    audit_sql = (_VERSIONS / "0003_audit_log.py").read_text(encoding="utf-8")
    weakened = audit_sql.replace("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM cv_ro", "")
    weakened = weakened.replace("CREATE TRIGGER trg_audit_no_truncate", "-- dropped")
    codes = [f.code for f in ov.static_findings(_latest_chain_sql(), weakened)]
    assert codes == ["static_revokes", "static_triggers"]
