"""Offline, read-only audit-integrity check (E43-T10, #1238; SR-063, C-5.7): the flow behind
`python -m candleviewer.audit_chain_verify`.

The entry point imports no `audit` (C-3.3), so this M21 module composes the run over the CLI's
read-only Postgres side (`VerifyStores`, M10's `SqlAlchemyAuditVerifyDatabase`) as
`admin.audit_break_ack` does. The chain is walked by `AuditQueryService.plan_verify` and
`run_verify`, the in-app verify's one walk, statement and budget, over the whole chain (genesis
to the head read when the run starts) with its database checkpoints. What is new here is only:

* the definitions (`--check`): the grant model on `audit_log` and `audit_checkpoints` (`cv_app`
  exactly SELECT and INSERT, `cv_ro` exactly SELECT, over all seven table privileges), the five
  guard triggers enabled, and the deployed `audit_chain()` framing `HASHED_FIELDS` in order;
* the checkpoint file (interim anchor), `--checkpoint-file`: every head it records must name an
  entry with the same hash, with `_check_range`'s kinds; its sha256 against the recorded one;
* the report and the exit codes.

A break is named as `audit_ack_break` names one (`first_bad_id`, `kind`). The tool writes nothing
and engages no halt: a break it finds is a tamper signal for an Owner-run `verifyAuditChain`.

Exit status: 0 every check passed; 1 a check failed (a break found); 2 a usage or settings error,
nothing ran; 3 stopped (a timeout, a read failure, an entry over the cap): never a pass.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol, cast

from candleviewer.admin.audited import audit_exempt
from candleviewer.audit.hashing import ChainHasherBusy
from candleviewer.audit.models import ChainBreakKind
from candleviewer.audit.query import VERIFY_BATCH_SIZE, AuditQueryService, chain_digest
from candleviewer.audit.repository import HASHED_FIELDS, AuditRepository
from candleviewer.audit.verify_runner import VerifyStopReason
from candleviewer.storage.errors import AuditEntryTooLarge, StorageTierUnavailable

__all__ = ["EXIT_FAIL", "EXIT_PASS", "EXIT_STOPPED", "EXIT_USAGE", "VerifyStores", "main", "run"]

EXIT_PASS, EXIT_FAIL, EXIT_USAGE, EXIT_STOPPED = 0, 1, 2, 3
DEFAULT_BATCH: Final = 2_000
#: Twice the scheduled run's 1 800 s: this run has one connection of its own rather than a share
#: of cv-api's pool and is meant for off-peak use; it stays within the 21 600 s cap that bounds
#: the scheduled run (`Settings.audit_verify_nightly_deadline_s`).
DEFAULT_TIMEOUT_S: Final = 3_600.0
TIMEOUT_MAX_S: Final = 21_600.0
#: A checkpoint file holds one short line per daily run; a larger file is refused unread.
FILE_MAX_BYTES: Final = 16 * 1024 * 1024
DISPOSE_TIMEOUT_S: Final = 10.0
#: The whole chain: no span cap, as the scheduled run's plan.
_WHOLE_CHAIN: Final = sys.maxsize
AUDIT_TABLES: Final = ("audit_log", "audit_checkpoints")
#: Every table privilege Postgres knows, so a grant outside the model is seen too.
TABLE_PRIVILEGES: Final = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
#: What each login holds on each audit table, exactly (C-5.7).
EXPECTED_GRANTS: Final = {"cv_app": frozenset({"SELECT", "INSERT"}), "cv_ro": frozenset({"SELECT"})}
#: Trigger name -> table, as `0003_audit_log` creates them.
EXPECTED_TRIGGERS: Final = {
    "trg_audit_chain": "audit_log",
    "trg_audit_append": "audit_log",
    "trg_audit_no_truncate": "audit_log",
    "trg_audit_ckpt_append": "audit_checkpoints",
    "trg_audit_ckpt_no_truncate": "audit_checkpoints",
}
_FIELD_REF: Final = re.compile(r"audit_field\(\s*(?:to_char\(\s*)?NEW\.([a-z_]+)")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")


class VerifyStores(Protocol):
    """The read-only database side (`SqlAlchemyAuditVerifyDatabase`)."""

    @property
    def audit_log(self) -> AuditRepository: ...

    async def held_privileges(
        self, roles: list[str], tables: list[str], privileges: list[str]
    ) -> dict[tuple[str, str], frozenset[str]]: ...

    async def triggers(self, tables: list[str]) -> dict[str, tuple[str, bool]]: ...

    async def chain_definition(self) -> str | None: ...

    async def dispose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Finding:
    """One failed check: ids, hashes, roles and privileges only, never an entry's fields."""

    section: str
    detail: str


@dataclass(frozen=True, slots=True)
class FileHead:
    head_id: int
    head_hash: str


class _Stopped(Exception):
    def __init__(self, reason: str, checked: int) -> None:
        super().__init__(reason)
        self.reason, self.checked = reason, checked


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: Sequence[str] | None = None, *, connect: Callable[[], VerifyStores | None]) -> int:
    """`connect` loads the settings and builds the stores, or returns `None` when no read-only
    login is configured; it opens no connection."""
    args = _parser().parse_args(argv)
    if args.self_test:
        return asyncio.run(self_test())
    if not 0 < args.timeout <= TIMEOUT_MAX_S:
        return _usage(f"--timeout must be above 0 and at most {TIMEOUT_MAX_S:.0f} s")
    if args.checkpoint_sha256 is not None and not _SHA256.fullmatch(args.checkpoint_sha256):
        return _usage("--checkpoint-sha256 must be 64 lower-case hex digits")
    data = None
    if args.checkpoint_file is not None:
        try:
            with Path(args.checkpoint_file).open("rb") as handle:
                data = handle.read(FILE_MAX_BYTES + 1)
        except OSError as exc:
            return _usage(f"the checkpoint file is unreadable ({type(exc).__name__})")
        if len(data) > FILE_MAX_BYTES:
            return _usage(f"the checkpoint file is over {FILE_MAX_BYTES} bytes")
    try:
        stores = connect()
    except Exception as exc:  # a pydantic ValidationError among them; never print a value
        return _usage(f"invalid settings ({type(exc).__name__})")
    if stores is None:
        return _usage("set CV_AUDIT_VERIFY_DSN to a read-only login; CV_PG_DSN is never used")
    run_args = (args.check, data, args.checkpoint_sha256, args.batch, args.timeout)
    return asyncio.run(run(stores, *run_args))


def _usage(why: str) -> int:
    sys.stderr.write(f"audit-chain-verify: {why}; nothing ran\n")
    return EXIT_USAGE


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m candleviewer.audit_chain_verify",
        description="Read-only check of the audit chain, its grants, guard triggers and hashed "
        "field order, and a checkpoint file. The login comes from CV_AUDIT_VERIFY_DSN. See "
        "docs/ops/runbooks/audit-chain-verify.md.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="the definitions only, no chain walk")
    mode.add_argument("--self-test", action="store_true", help="run on a seeded chain; no DB")
    parser.add_argument("--checkpoint-file", help="a checkpoint file (JSON lines) to compare")
    parser.add_argument("--checkpoint-sha256", help="the file's sha256 as it was recorded")
    parser.add_argument(
        "--batch",
        type=int,
        default=DEFAULT_BATCH,
        choices=range(1, VERIFY_BATCH_SIZE + 1),
        metavar=f"1..{VERIFY_BATCH_SIZE}",
        help="entries per read (default %(default)s)",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="seconds (default %(default)s)"
    )
    return parser


async def run(
    stores: VerifyStores,
    check_only: bool = False,
    data: bytes | None = None,
    sha256: str | None = None,
    batch: int = DEFAULT_BATCH,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> int:
    """One check over `stores`, whose pool is released at the end."""
    try:
        found = await _checks(stores, check_only, data, sha256, batch, timeout_s)
    except _Stopped as stop:
        _out(f"STOPPED: {stop.reason} (entries_checked={stop.checked}); result unknown")
        return EXIT_STOPPED
    finally:
        await _dispose(stores)
    _out(f"RESULT: {'FAIL' if found else 'PASS'} ({len(found)} FAIL)")
    return EXIT_FAIL if found else EXIT_PASS


async def _checks(
    stores: VerifyStores,
    check_only: bool,
    data: bytes | None,
    sha256: str | None,
    batch: int,
    timeout_s: float,
) -> list[Finding]:
    checked = 0
    try:
        async with asyncio.timeout(timeout_s):
            found = await definitions(stores)
            if check_only:
                return found
            query = AuditQueryService(stores.audit_log)
            try:
                plan = await query.plan_verify(from_id=None, to_id=None, max_span=_WHOLE_CHAIN)
                result = await query.run_verify(plan, batch_size=batch)
            finally:
                query.close()
            checked = result.entries_checked
            note = f"entries_checked={checked}, head id {plan.head_id}"
            if not result.verified:
                kind = result.kind or "unknown"
                chain = [Finding("chain", f"first_bad_id={result.first_bad_id} kind={kind}")]
                found += _section("chain", chain, note)
                if data is not None:
                    _out("SKIP checkpoint-file: compared only against a chain with no break")
                return found
            found += _section("chain", [], note)
            if data is not None:
                heads, problems = parse_heads(data)
                problems += await compare_heads(stores.audit_log, heads, plan.head_id)
                digest = hashlib.sha256(data).hexdigest()
                if sha256 is not None and digest != sha256:
                    problems.append(Finding("checkpoint-file", f"sha256 {digest} != {sha256}"))
                found += _section("checkpoint-file", problems, f"{len(heads)} heads")
            return found
    except Exception as exc:  # a stop: never a pass (a cancel is no `Exception`: it propagates)
        raise _Stopped(stop_reason(exc), checked) from None


def stop_reason(exc: BaseException) -> str:
    """The scheduled run's stop vocabulary (`VerifyStopReason`); a store error adds its SQLSTATE
    and any other its class, never its text (a driver's text can name the host or the login)."""
    if isinstance(exc, TimeoutError):
        return VerifyStopReason.TIMEOUT.value
    if isinstance(exc, ChainHasherBusy):
        return VerifyStopReason.HASHER_BUSY.value
    if isinstance(exc, AuditEntryTooLarge):
        return f"{VerifyStopReason.ENTRY_TOO_LARGE.value}@{exc.entry_id}"
    state = getattr(exc, "sqlstate", None)
    suffix = f" sqlstate={state}" if isinstance(state, str) else ""
    if isinstance(exc, StorageTierUnavailable):
        return f"{VerifyStopReason.STORE_UNAVAILABLE.value}{suffix}"
    return f"{VerifyStopReason.INTERNAL_ERROR.value} ({type(exc).__name__}{suffix})"


async def definitions(stores: VerifyStores) -> list[Finding]:
    """The grants, the guard triggers and the deployed `audit_chain()` field order."""
    held = await stores.held_privileges(
        list(EXPECTED_GRANTS), list(AUDIT_TABLES), list(TABLE_PRIVILEGES)
    )
    found = _section("grants", check_grants(held))
    found += _section("triggers", check_triggers(await stores.triggers(list(AUDIT_TABLES))))
    order = framed_fields(await stores.chain_definition() or "")
    fields = [] if order == ("prev_hash", *HASHED_FIELDS) else [Finding("fields", f"{order}")]
    return found + _section("fields", fields)


def check_grants(held: dict[tuple[str, str], frozenset[str]]) -> list[Finding]:
    found: list[Finding] = []
    for role, expected in sorted(EXPECTED_GRANTS.items()):
        for table in AUDIT_TABLES:
            got = held.get((role, table))
            if got is None:
                found.append(Finding("grants", f"{role} on {table}: role or table missing"))
            elif got != expected:
                extra, missing = sorted(got - expected), sorted(expected - got)
                detail = f"{role} on {table}: extra {extra}, missing {missing}"
                found.append(Finding("grants", detail))
    return found


def check_triggers(present: dict[str, tuple[str, bool]]) -> list[Finding]:
    found: list[Finding] = []
    for name, table in sorted(EXPECTED_TRIGGERS.items()):
        got = present.get(name)
        if got is None or got[0] != table:
            found.append(Finding("triggers", f"{name} on {table}: absent"))
        elif not got[1]:
            found.append(Finding("triggers", f"{name} on {table}: disabled"))
    return found


def framed_fields(definition: str) -> tuple[str, ...]:
    """The columns `audit_chain()` frames with `audit_field`, in order."""
    return tuple(_FIELD_REF.findall(definition))


def parse_heads(data: bytes) -> tuple[list[FileHead], list[Finding]]:
    """The checkpoint job's JSON lines: each a `head_id` and a `head_hash`. A line that is not
    one is a finding, never skipped."""
    heads: list[FileHead] = []
    problems: list[Finding] = []
    for number, raw in enumerate(data.decode("utf-8", "replace").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            record = None
        record = record if isinstance(record, dict) else {}
        head_id, head_hash = record.get("head_id"), record.get("head_hash")
        if type(head_id) is int and head_id > 0 and isinstance(head_hash, str):
            if _SHA256.fullmatch(head_hash):
                heads.append(FileHead(head_id, head_hash))
                continue
        problems.append(Finding("checkpoint-file", f"line {number}: not a checkpoint head"))
    return heads, problems


async def compare_heads(
    repository: AuditRepository, heads: Sequence[FileHead], head_id: int
) -> list[Finding]:
    """Each file head against the stored `entry_hash` of the entry it names, which the walk up to
    `head_id` has just authenticated: `_check_range`'s kinds. A head above `head_id` is a later
    append when its entry has that hash, and a truncated tail otherwise."""
    found: list[Finding] = []
    for head in heads:
        stored = await repository.fetch_entry_hash(head.head_id)
        if stored == head.head_hash:
            continue
        if head.head_id > head_id:
            kind = ChainBreakKind.TAIL_TRUNCATED
        elif stored is None:
            kind = ChainBreakKind.CHECKPOINT_MISSING
        else:
            kind = ChainBreakKind.CHECKPOINT_MISMATCH
        detail = f"first_bad_id={head.head_id} kind={kind} (file {head.head_hash}, chain {stored})"
        found.append(Finding("checkpoint-file", detail))
    return found


def _section(name: str, found: list[Finding], note: str = "") -> list[Finding]:
    for finding in found:
        _out(f"FAIL {finding.section}: {finding.detail}")
    if not found:
        _out(f"PASS {name}" + (f" ({note})" if note else ""))
    elif note:
        _out(f"     {name}: {note}")
    return found


async def _dispose(stores: VerifyStores) -> None:
    try:
        async with asyncio.timeout(DISPOSE_TIMEOUT_S):
            await stores.dispose()
    except Exception as exc:  # the run has ended; exiting releases the rest
        sys.stderr.write(f"audit-chain-verify: pool not released ({type(exc).__name__})\n")


# --- `--self-test`: every check on a seeded chain, no database ---------------------------------


class SeededStores:
    """An in-memory `VerifyStores` over a seeded chain (the self-test and the unit tests)."""

    def __init__(self, count: int = 8) -> None:
        self.rows: list[tuple[Any, ...]] = []
        prev = "0" * 64
        for n in range(1, count + 1):
            values = [None, f"seed-{n}", None, None, "audit.seed", "seed", str(n), "success"]
            values += ["info", None, None, json.dumps({"n": n, "é": "zé"}), None, "demo"]
            values.append(f"2026-11-04T00:00:{n:02d}.000000+00")
            entry = chain_digest(prev, values)
            self.rows.append((2 * n, prev, entry, *values))  # ids with gaps, as the table has
            prev = entry
        self.held = {(r, t): e for r, e in EXPECTED_GRANTS.items() for t in AUDIT_TABLES}
        self.present = {name: (table, True) for name, table in EXPECTED_TRIGGERS.items()}
        rendered = ", ".join(f"audit_field(NEW.{f})" for f in ("prev_hash", *HASHED_FIELDS))
        self.definition = f"BEGIN NEW.entry_hash := sha256({rendered}); END"
        self.checkpoints: list[tuple[int, str]] = []
        self.disposed = False

    @property
    @audit_exempt("read")
    def audit_log(self) -> AuditRepository:
        return cast(AuditRepository, self)

    @audit_exempt("read")
    async def held_privileges(
        self, roles: list[str], tables: list[str], privileges: list[str]
    ) -> dict[tuple[str, str], frozenset[str]]:
        return dict(self.held)

    @audit_exempt("read")
    async def triggers(self, tables: list[str]) -> dict[str, tuple[str, bool]]:
        return dict(self.present)

    @audit_exempt("read")
    async def chain_definition(self) -> str | None:
        return self.definition

    @audit_exempt("lifecycle")
    async def dispose(self) -> None:
        self.disposed = True

    @audit_exempt("read")
    async def read_bounds(self) -> tuple[int, int] | None:
        return (self.rows[0][0], self.rows[-1][0]) if self.rows else None

    @audit_exempt("read")
    async def fetch_anchor_hash(self, before_id: int) -> str | None:
        below = [r[2] for r in self.rows if r[0] < before_id]
        return str(below[-1]) if below else None

    @audit_exempt("read")
    async def fetch_entry_hash(self, entry_id: int) -> str | None:
        return next((str(r[2]) for r in self.rows if r[0] == entry_id), None)

    @audit_exempt("read")
    async def fetch_verify_batch(
        self, *, after_id: int, to_id: int, limit: int
    ) -> list[tuple[Any, ...]]:
        return [r for r in self.rows if after_id < r[0] <= to_id][:limit]

    @audit_exempt("read")
    async def fetch_checkpoints(self, to_id: int) -> list[tuple[int, str, str | None]]:
        mine = [(h, hh) for h, hh in self.checkpoints if h <= to_id]
        return [(h, hh, await self.fetch_entry_hash(h)) for h, hh in mine]

    @audit_exempt("read")
    async def fetch_checkpoint_above(self, head_id: int) -> int | None:
        above = [h for h, hh in self.checkpoints if h > head_id]
        return min(above, default=None)


_OFF: Final = ("audit_log", False)


def _file(*heads: tuple[int, str]) -> bytes:
    return "".join(json.dumps({"head_id": h, "head_hash": hh}) + "\n" for h, hh in heads).encode()


async def self_test() -> int:
    """Each check on a seeded chain: the clean chain passes and every injected fault is named
    with the exit code it must give."""
    widened = {("cv_ro", "audit_log"): frozenset(TABLE_PRIVILEGES)}
    cases: list[tuple[str, Callable[[SeededStores], Any], int]] = [
        ("clean chain", lambda s: None, EXIT_PASS),
        ("changed entry", lambda s: _replace(s, 4, 14, '{"n": 5}'), EXIT_FAIL),
        ("dropped entry", lambda s: s.rows.pop(3), EXIT_FAIL),
        ("re-ordered entries", lambda s: _swap(s, 2, 3), EXIT_FAIL),
        ("checkpoint above the head", lambda s: s.checkpoints.append((99, "a" * 64)), EXIT_FAIL),
        ("widened grant", lambda s: s.held.update(widened), EXIT_FAIL),
        ("disabled guard", lambda s: s.present.update(trg_audit_append=_OFF), EXIT_FAIL),
        ("field order", lambda s: setattr(s, "definition", ""), EXIT_FAIL),
    ]
    failed = 0
    for name, inject, expected in cases:
        stores = SeededStores()
        inject(stores)
        got = await run(stores)
        failed += got != expected
        _out(f"{'PASS' if got == expected else 'FAIL'} self-test {name}: exit {got}")
    stores = SeededStores()
    head_id, head_hash = stores.rows[-1][0], str(stores.rows[-1][2])
    for name, data, expected in [
        ("checkpoint file equal", _file((head_id, head_hash)), EXIT_PASS),
        ("checkpoint file diverges", _file((head_id, "f" * 64)), EXIT_FAIL),
        ("checkpoint file ahead", _file((head_id + 2, head_hash)), EXIT_FAIL),
    ]:
        got = await run(SeededStores(), data=data)
        failed += got != expected
        _out(f"{'PASS' if got == expected else 'FAIL'} self-test {name}: exit {got}")
    _out(f"SELF-TEST: {'FAIL' if failed else 'PASS'} ({failed} FAIL)")
    return EXIT_FAIL if failed else EXIT_PASS


def _replace(stores: SeededStores, index: int, column: int, value: str) -> None:
    row = stores.rows[index]
    stores.rows[index] = (*row[:column], value, *row[column + 1 :])


def _swap(stores: SeededStores, a: int, b: int) -> None:
    rows = stores.rows
    rows[a], rows[b] = (rows[a][0], *rows[b][1:]), (rows[b][0], *rows[a][1:])
