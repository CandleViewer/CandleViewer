"""Offline, read-only audit-integrity check (E43-T10; SR-063, SR-068, C-5.7, US-ADMIN-008).

    python -m candleviewer.audit_chain_verify [--mirror FILE] [--mirror-sha256 HEX]
    python -m candleviewer.audit_chain_verify --check
    python -m candleviewer.audit_chain_verify --self-test

The flow lives here; the entry point `candleviewer.audit_chain_verify` hands it the read-only
Postgres reader (M21 imports no storage driver, ADR-0003).

The default run reads the database named by `CV_AUDIT_VERIFY_DSN` (a `cv_ro` login is enough;
every session is opened read-only) and checks, in order: the grant model and the guard triggers
of the audit tables, the whole hash chain from genesis to the head, the database checkpoints,
and, with `--mirror`, the off-box mirror file against the chain (and its sha256 against the value
the off-box target recorded, with `--mirror-sha256`). `--check` compares the tool's expectations
with the shipped migrations; `--self-test` runs the checks on a seeded chain with a changed, a
dropped and a re-ordered entry. Neither touches a database. Output is one line per check; it
names ids, hashes, roles and privileges only, never the connection string or an entry's fields.
Runbook: `docs/ops/runbooks/audit-chain-verify.md`.

Exit status: 0 every check passed; 1 a check failed; 2 nothing could be checked (usage, no
connection string, the database unreachable or a read refused).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, Protocol

from candleviewer.audit import offline_verify as ov

DSN_ENV: Final = "CV_AUDIT_VERIFY_DSN"
EXIT_PASS, EXIT_FAIL, EXIT_UNCHECKED = 0, 1, 2
DEFAULT_BATCH: Final = 2_000
DEFAULT_TIMEOUT_S: Final = 3_600.0
_VERSIONS: Final = Path(__file__).resolve().parents[1] / "migrations" / "versions"
_AUDIT_MIGRATION: Final = "0003_audit_log.py"
_CHAIN_DEF: Final = re.compile(r"CREATE (?:OR REPLACE )?FUNCTION audit_chain\(\).*?\$BODY\$;", re.S)
_SHA256: Final = re.compile(r"[0-9a-f]{64}")


class OfflineReader(Protocol):
    """The read-only database side (`SqlAlchemyAuditOfflineReader`)."""

    @property
    def audit(self) -> Any:
        """The audit repository's verify reads (`read_head`, `fetch_checkpoints`,
        `fetch_checkpoint_above`, `fetch_verify_batch`)."""
        ...

    async def held_privileges(
        self, roles: list[str], tables: list[str], privileges: list[str]
    ) -> dict[tuple[str, str], frozenset[str]]: ...

    async def triggers(self, tables: list[str]) -> dict[str, tuple[str, bool]]: ...

    async def close(self) -> None: ...


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(
    argv: Sequence[str] | None = None,
    open_reader: Callable[[str], OfflineReader] | None = None,
) -> int:
    """`open_reader` builds the reader from the connection string; without one only `--check`
    and `--self-test` run."""
    args = _parser().parse_args(argv)
    if args.check:
        return _report(static_check(_VERSIONS))
    if args.self_test:
        return self_test()
    if args.mirror_sha256 is not None and not _SHA256.fullmatch(args.mirror_sha256):
        sys.stderr.write("audit-chain-verify: --mirror-sha256 must be 64 lower-case hex\n")
        return EXIT_UNCHECKED
    dsn = os.environ.get(DSN_ENV, "")
    if not dsn or open_reader is None:
        sys.stderr.write(f"audit-chain-verify: set {DSN_ENV}; nothing checked\n")
        return EXIT_UNCHECKED
    mirror: bytes | None = None
    if args.mirror is not None:
        try:
            mirror = Path(args.mirror).read_bytes()
        except OSError as exc:
            sys.stderr.write(f"audit-chain-verify: mirror unreadable ({type(exc).__name__})\n")
            return EXIT_UNCHECKED
    return asyncio.run(
        run(
            open_reader(dsn),
            mirror=mirror,
            mirror_sha256=args.mirror_sha256,
            batch=args.batch,
            timeout_s=args.timeout,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m candleviewer.audit_chain_verify",
        description="Read-only check of the audit chain, its grants and its off-box mirror. "
        f"The database comes from {DSN_ENV}. See docs/ops/runbooks/audit-chain-verify.md.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="compare with the migrations; no DB")
    mode.add_argument("--self-test", action="store_true", help="run on a seeded chain; no DB")
    parser.add_argument("--mirror", help="the off-box mirror file (JSON lines) to compare")
    parser.add_argument("--mirror-sha256", help="the mirror file's sha256 as the target recorded")
    parser.add_argument(
        "--batch",
        type=int,
        default=DEFAULT_BATCH,
        choices=range(1, 10_001),
        metavar="1..10000",
        help="entries per read (default %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="seconds for the whole run (default %(default)s)",
    )
    return parser


async def run(
    reader: OfflineReader,
    *,
    mirror: bytes | None = None,
    mirror_sha256: str | None = None,
    batch: int = DEFAULT_BATCH,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> int:
    """One check over `reader`, whose pool is released at the end."""
    try:
        async with asyncio.timeout(timeout_s):
            findings = await _checks(reader, mirror, mirror_sha256, batch)
    except TimeoutError:
        sys.stderr.write("audit-chain-verify: the run timed out; result unknown\n")
        return EXIT_UNCHECKED
    except Exception as exc:  # any read failure: the result is unknown, never a pass
        # The class and a SQLSTATE only: a driver's text can name the host or the login.
        state = getattr(exc, "sqlstate", None)
        why = type(exc).__name__ + (f", sqlstate {state}" if isinstance(state, str) else "")
        sys.stderr.write(f"audit-chain-verify: a read failed ({why}); result unknown\n")
        return EXIT_UNCHECKED
    finally:
        await reader.close()
    return _report(findings)


async def _checks(
    reader: OfflineReader,
    mirror: bytes | None,
    mirror_sha256: str | None,
    batch: int,
) -> list[ov.Finding]:
    tables, roles = list(ov.AUDIT_TABLES), list(ov.APP_ROLES)
    held = await reader.held_privileges(roles, tables, list(ov.TABLE_PRIVILEGES))
    findings = _section("grants", ov.check_grants(held))
    findings += _section("triggers", ov.check_triggers(await reader.triggers(tables)))
    heads, problems = ov.parse_mirror(mirror.decode("utf-8", "replace")) if mirror else ([], [])
    head = await reader.audit.read_head()
    head_id = head[0] if head else 0
    checkpoints = [
        ov.MirrorHead(h, hh) for h, hh, _ in await reader.audit.fetch_checkpoints(head_id)
    ]
    walker = ov.ChainWalker(watch=frozenset(h.head_id for h in (*heads, *checkpoints)))
    after = 0
    while after < head_id:
        rows = await reader.audit.fetch_verify_batch(after_id=after, to_id=head_id, limit=batch)
        if not rows or not walker.feed(rows):
            break
        after = int(rows[-1][0])
    chain = [walker.first_break] if walker.first_break else []
    if not chain and head is not None and (walker.head_id, walker.head_hash) != head:
        chain.append(ov.Finding("chain_head_mismatch", f"walk ended at id {walker.head_id}"))
    findings += _section("chain", chain, f"{walker.checked} entries, head id {walker.head_id}")
    if chain:
        return findings  # heads are compared only against an intact chain
    stored = ov.compare_heads("checkpoint", checkpoints, walker)
    above = await reader.audit.fetch_checkpoint_above(walker.head_id)
    if above is not None:  # a checkpoint names an id past the local head: the tail is gone
        detail = f"checkpoint head id {above} is above the local head id {walker.head_id}"
        stored.append(ov.Finding("checkpoint_ahead_of_local", detail))
    findings += _section("checkpoints", stored)
    if mirror is not None:
        mirrored = problems + ov.compare_heads("mirror", heads, walker)
        digest = ov.mirror_digest(mirror)
        if mirror_sha256 is not None and digest != mirror_sha256:
            mirrored.append(ov.Finding("mirror_file_digest", f"{digest} != {mirror_sha256}"))
        findings += _section("mirror", mirrored, f"{len(heads)} heads, sha256 {digest}")
    return findings


def _section(name: str, findings: list[ov.Finding], note: str = "") -> list[ov.Finding]:
    for finding in findings:
        _out(finding.line())
    if not findings:
        _out(f"PASS {name}" + (f" ({note})" if note else ""))
    return findings


def _report(findings: list[ov.Finding]) -> int:
    _out(f"RESULT: {'FAIL' if findings else 'PASS'} ({len(findings)} FAIL)")
    return EXIT_FAIL if findings else EXIT_PASS


def static_check(versions: Path) -> list[ov.Finding]:
    """The tool's expectations against the migrations in `versions`: the latest definition of
    `audit_chain()` (the highest-numbered revision that defines it) and `0003_audit_log`."""
    chain_sql = ""
    for path in sorted(versions.glob("[0-9]*.py")):
        found = _CHAIN_DEF.search(path.read_text(encoding="utf-8"))
        chain_sql = found.group(0) if found else chain_sql
    audit_sql = (versions / _AUDIT_MIGRATION).read_text(encoding="utf-8")
    return _section("static", ov.static_findings(chain_sql, audit_sql))


def self_test() -> int:
    """Each check on a seeded chain: the clean chain passes and every injected fault is named."""
    rows = ov.seed_rows(8)
    swapped = list(rows)
    swapped[2], swapped[3] = (rows[2][0], *rows[3][1:]), (rows[3][0], *rows[2][1:])
    tampered = list(rows)
    tampered[4] = (*rows[4][:14], '{"n": 5, "label": "changed"}', *rows[4][15:])
    head_id, head_hash = int(str(rows[-1][0])), str(rows[-1][2])
    good = ov.MirrorHead(head_id, head_hash)
    expected_ok = dict(ov.EXPECTED_GRANTS)
    widened = {**expected_ok, ("cv_app", "audit_log"): frozenset({"SELECT", "INSERT", "UPDATE"})}
    on = {name: (table, True) for name, table in ov.EXPECTED_TRIGGERS.items()}
    off = {**on, "trg_audit_append": ("audit_log", False)}
    cases: list[tuple[str, Callable[[], list[str]], list[str]]] = [
        ("clean chain", lambda: _codes(ov.walk(rows)), []),
        ("changed entry", lambda: _codes(ov.walk(tampered)), ["chain_entry_hash_mismatch@10"]),
        (
            "dropped entry",
            lambda: _codes(ov.walk(rows[:3] + rows[4:])),
            ["chain_prev_hash_mismatch@10"],
        ),
        ("re-ordered entries", lambda: _codes(ov.walk(swapped)), ["chain_prev_hash_mismatch@6"]),
        ("mirror equal", lambda: _mirror([good], rows), []),
        (
            "mirror divergence",
            lambda: _mirror([ov.MirrorHead(head_id, "f" * 64)], rows),
            ["mirror_divergence"],
        ),
        (
            "mirror ahead",
            lambda: _mirror([ov.MirrorHead(head_id + 2, head_hash)], rows),
            ["mirror_ahead_of_local"],
        ),
        ("grants as declared", lambda: [f.code for f in ov.check_grants(expected_ok)], []),
        ("grant widened", lambda: [f.code for f in ov.check_grants(widened)], ["grant_mismatch"]),
        ("guard disabled", lambda: [f.code for f in ov.check_triggers(off)], ["trigger_disabled"]),
    ]
    failed = 0
    for name, case, expected in cases:
        got = case()
        failed += got != expected
        _out(f"{'PASS' if got == expected else 'FAIL'} self-test {name}: {got or 'no finding'}")
    _out(f"RESULT: {'FAIL' if failed else 'PASS'} ({failed} FAIL)")
    return EXIT_FAIL if failed else EXIT_PASS


def _codes(walker: ov.ChainWalker) -> list[str]:
    found = walker.first_break
    if found is None:
        return []
    at = re.search(r"at id (\d+)", found.detail)
    return [f"{found.code}@{at.group(1) if at else '?'}"]


def _mirror(heads: list[ov.MirrorHead], rows: list[tuple[object, ...]]) -> list[str]:
    walker = ov.walk(rows, watch=(h.head_id for h in heads))
    return [f.code for f in ov.compare_heads("mirror", heads, walker)]
