"""Offline, read-only audit-integrity check (E43-T10, #1238; SR-063, C-5.7), the flow behind
`python -m candleviewer.audit_chain_verify`. The entry point imports no `audit` (C-3.3), so this
M21 module composes the run over the CLI's read-only Postgres side (`VerifyStores`, M10's
`SqlAlchemyAuditVerifyDatabase`) as `admin.audit_break_ack` does. The chain is walked by the
in-app verify's one walk, statement and budget (`AuditQueryService.plan_verify`, `run_verify`),
genesis to the head read at start, with its database checkpoints. New here: the definitions
(`--check`: `cv_app` exactly SELECT and INSERT and `cv_ro` exactly SELECT on `audit_log` and
`audit_checkpoints`, over all seven table privileges, column grants and every role a login can
become included; the five guard triggers firing for an ordinary session in the shape
`0003_audit_log` gives them, with every `session_replication_role` that applies `origin`; the
deployed `audit_chain()` framing exactly `HASHED_FIELDS` in order, a shape the reader does not
know being a finding); the checkpoint file (interim anchor: each head names an entry with the
same hash, with `_check_range`'s kinds, and its sha256 is the recorded one); the report and the
exit codes.

A break is named as `audit_ack_break` names one (`first_bad_id`, `kind`). The tool writes nothing
and engages no halt: a break it finds is a tamper signal for an Owner-run `verifyAuditChain`.
Exit status: 0 every check passed; 1 a check failed; 2 a usage or settings error, nothing ran;
3 stopped (a timeout, a read failure, an entry over the cap): never a pass.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterator, Sequence
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
#: Twice the scheduled 1 800 s (own connection, off-peak); cap `audit_verify_nightly_deadline_s`.
DEFAULT_TIMEOUT_S: Final = 3_600.0
TIMEOUT_MAX_S: Final = 21_600.0
#: A checkpoint file holds one short line per daily run; a larger file is refused unread.
FILE_MAX_BYTES: Final = 16 * 1024 * 1024
DISPOSE_TIMEOUT_S: Final = 10.0
#: The whole chain: no span cap, as the scheduled run's plan.
_WHOLE_CHAIN: Final = sys.maxsize
AUDIT_TABLES: Final = ("audit_log", "audit_checkpoints")
#: Every table privilege Postgres knows, so a grant outside the model is seen too.
TABLE_PRIVILEGES: Final = tuple("SELECT INSERT UPDATE DELETE TRUNCATE REFERENCES TRIGGER".split())
#: What each login holds on each audit table, exactly (C-5.7).
EXPECTED_GRANTS: Final = {"cv_app": frozenset({"SELECT", "INSERT"}), "cv_ro": frozenset({"SELECT"})}
#: Trigger name -> (table, shape), as `0003_audit_log` creates them. The shape is the store's:
#: the `tgtype` bits (1 row, 2 before, 4 insert, 8 delete, 16 update, 32 truncate) and the
#: function; a WHEN clause or an `UPDATE OF` column list would add a word.
_ROW_INSERT, _ROW_UPDATE_DELETE, _TRUNCATE = "type=7", "type=27", "type=34"
EXPECTED_TRIGGERS: Final = {
    "trg_audit_chain": ("audit_log", f"{_ROW_INSERT} function=public.audit_chain"),
    "trg_audit_append": ("audit_log", f"{_ROW_UPDATE_DELETE} function=public.forbid_mutation"),
    "trg_audit_no_truncate": ("audit_log", f"{_TRUNCATE} function=public.audit_refuse_truncate"),
    "trg_audit_ckpt_append": (
        "audit_checkpoints",
        f"{_ROW_UPDATE_DELETE} function=public.forbid_mutation",
    ),
    "trg_audit_ckpt_no_truncate": (
        "audit_checkpoints",
        f"{_TRUNCATE} function=public.audit_refuse_truncate",
    ),
}
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
#: `head_id` is a Postgres `bigint`.
_BIGINT_MAX: Final = 2**63 - 1
TIMEOUT_MIN_S: Final = 1.0


class VerifyStores(Protocol):
    """The read-only database side (`SqlAlchemyAuditVerifyDatabase`)."""

    @property
    def audit_log(self) -> AuditRepository: ...

    async def held_privileges(
        self, roles: list[str], tables: list[str], privileges: list[str]
    ) -> dict[tuple[str, str], frozenset[str]]: ...

    async def triggers(self, tables: list[str]) -> dict[tuple[str, str], tuple[bool, str]]: ...

    async def replication_roles(self) -> list[tuple[str, str]]: ...

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
    def __init__(self, reason: str, checked: int, failed: int) -> None:
        super().__init__(reason)
        self.reason, self.checked, self.failed = reason, checked, failed


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: Sequence[str] | None = None, *, connect: Callable[[], VerifyStores | None]) -> int:
    """`connect` builds the stores from the settings (`None`: no read-only login); opens nothing."""
    args = _parser().parse_args(argv)
    if args.self_test:
        given = (args.checkpoint_file, args.checkpoint_sha256, args.batch, args.timeout)
        if any(value is not None for value in given):
            return _usage("--self-test takes no other option")
        return asyncio.run(self_test())
    batch = DEFAULT_BATCH if args.batch is None else args.batch
    timeout = DEFAULT_TIMEOUT_S if args.timeout is None else args.timeout
    if not TIMEOUT_MIN_S <= timeout <= TIMEOUT_MAX_S:
        limits = f"{TIMEOUT_MIN_S:.0f} to {TIMEOUT_MAX_S:.0f}"
        return _usage(f"--timeout must be {limits} s")
    if args.check and args.checkpoint_file is not None:
        return _usage("--check walks no chain, so it compares no checkpoint file")
    if args.checkpoint_sha256 is not None and not _SHA256.fullmatch(args.checkpoint_sha256):
        return _usage("--checkpoint-sha256 must be 64 lower-case hex digits")
    if args.checkpoint_sha256 is not None and args.checkpoint_file is None:
        return _usage("--checkpoint-sha256 needs --checkpoint-file")
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
    run_args = (args.check, data, args.checkpoint_sha256, batch, timeout)
    return asyncio.run(run(stores, *run_args))


def _usage(why: str) -> int:
    sys.stderr.write(f"audit-chain-verify: {why}; nothing ran\n")
    return EXIT_USAGE


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m candleviewer.audit_chain_verify",
        description="Read-only check of the audit chain, grants, guard triggers, hashed field "
        "order and a checkpoint file; login CV_AUDIT_VERIFY_DSN. See docs/ops/runbooks.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="the definitions only, no chain walk")
    mode.add_argument("--self-test", action="store_true", help="run on a seeded chain; no DB")
    parser.add_argument("--checkpoint-file", help="a checkpoint file (JSON lines) to compare")
    parser.add_argument("--checkpoint-sha256", help="the file's sha256 as it was recorded")
    parser.add_argument(
        "--batch",
        type=_batch,
        metavar=_BATCH_RANGE,
        help=f"entries per read (default {DEFAULT_BATCH})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        metavar=f"{TIMEOUT_MIN_S:.0f}..{TIMEOUT_MAX_S:.0f}",
        help=f"seconds for the whole run (default {DEFAULT_TIMEOUT_S:.0f})",
    )
    return parser


_BATCH_RANGE: Final = f"1..{VERIFY_BATCH_SIZE}"


def _batch(text: str) -> int:
    """`--batch`: an integer in `_BATCH_RANGE`; the error names the range, not every choice."""
    try:
        value = int(text)
    except ValueError:
        value = 0
    if not 1 <= value <= VERIFY_BATCH_SIZE:
        raise argparse.ArgumentTypeError(f"must be an integer in {_BATCH_RANGE}")
    return value


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
    except _Stopped as stop:  # a check that already failed keeps its exit code: never softened
        _out(f"STOPPED: {stop.reason} (entries_checked={stop.checked}); result unknown")
        return EXIT_FAIL if stop.failed else EXIT_STOPPED
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
    checked, found = 0, list[Finding]()
    try:
        async with asyncio.timeout(timeout_s):
            await definitions(stores, found)
            if check_only:
                if data is not None:
                    _out("SKIP checkpoint-file: --check walks no chain to compare it with")
                return found
            query = AuditQueryService(stores.audit_log)
            try:
                plan = await query.plan_verify(from_id=None, to_id=None, max_span=_WHOLE_CHAIN)
                result = await query.run_verify(plan, batch_size=batch)
            finally:  # a stop mid-walk reports the entries the walk had already checked
                checked = query.entries_walked
                query.close()
            checked = result.entries_checked
            if plan.from_id is not None and not result.full_chain:  # a pass covers the whole chain
                raise RuntimeError("the walk did not cover genesis to the head")
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
                if not heads:
                    problems.append(Finding("checkpoint-file", "no checkpoint head in the file"))
                problems += await compare_heads(stores.audit_log, heads, plan.head_id)
                digest = hashlib.sha256(data).hexdigest()
                if sha256 is not None and digest != sha256:
                    problems.append(Finding("checkpoint-file", f"sha256 {digest} != {sha256}"))
                found += _section("checkpoint-file", problems, f"{len(heads)} heads")
            return found
    except Exception as exc:  # a stop: never a pass (a cancel is no `Exception`: it propagates)
        raise _Stopped(stop_reason(exc), checked, len(found)) from None


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


async def definitions(stores: VerifyStores, found: list[Finding]) -> list[Finding]:
    """The grants, the guard triggers and the deployed `audit_chain()` field order, each
    section's findings added to `found` as soon as it ends (a later stop keeps them)."""
    held = await stores.held_privileges(
        list(EXPECTED_GRANTS), list(AUDIT_TABLES), list(TABLE_PRIVILEGES)
    )
    found += _section("grants", check_grants(held))
    present = await stores.triggers(list(AUDIT_TABLES))
    found += _section("triggers", check_triggers(present, await stores.replication_roles()))
    found += _section("fields", check_fields(await stores.chain_definition()))
    return found


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


def check_triggers(
    present: dict[tuple[str, str], tuple[bool, str]], replication: Sequence[tuple[str, str]]
) -> list[Finding]:
    """Each guard trigger on its table, firing, and of the shape `0003_audit_log` gives it; each
    applying replication role `origin`."""
    found: list[Finding] = []
    for where, value in replication:
        if value.strip().lower() != "origin":
            found.append(Finding("triggers", f"session_replication_role {value!r} ({where})"))
    for name, (table, shape) in sorted(EXPECTED_TRIGGERS.items()):
        got = present.get((name, table))
        if got is None:
            found.append(Finding("triggers", f"{name} on {table}: absent"))
            continue
        if got[0] is not True:
            found.append(Finding("triggers", f"{name} on {table}: disabled"))
        if got[1] != shape:
            found.append(Finding("triggers", f"{name} on {table}: {got[1]}, expected {shape}"))
    return found


# --- `fields`: the deployed `audit_chain()` against `HASHED_FIELDS` ----------------------------

#: The one statement that sets the hash, as 0003 and 0045 write it.
_ENTRY_HASH: Final = re.compile(r"\bNEW\.entry_hash\s*:=\s*encode\(\s*digest\(")
_DIGEST_TAIL: Final = re.compile(r"\s*,\s*'hex'\s*\)\s*;")
#: A framed column: `audit_field(NEW.<col>)`, optionally cast to text.
_PLAIN_TERM: Final = re.compile(r"audit_field\(\s*NEW\.([a-z_]+)(?:\s*::\s*text)?\s*\)")
#: `event_ts`, framed in the rendering the verifier reads (`fetch_verify_batch`).
_EVENT_TS_TERM: Final = re.compile(
    r"audit_field\(\s*to_char\(\s*NEW\.event_ts\s+AT\s+TIME\s+ZONE\s+'UTC'\s*,\s*"
    r"'YYYY-MM-DD\"T\"HH24:MI:SS\.USOF'\s*\)\s*\)"
)
#: The other uses of NEW the function may make: the three columns it sets, and its return.
_SETS: Final = re.compile(r"\bNEW\.(id|prev_hash|entry_hash)\s*:=")
_RETURN_NEW: Final = re.compile(r"\bRETURN\s+NEW\s*;")
_NEW: Final = re.compile(r"\bNEW\b", re.IGNORECASE)


class _Unparsed(ValueError):
    """A definition the `fields` reader does not understand: a finding, never a pass."""


def check_fields(definition: str | None) -> list[Finding]:
    """The deployed `audit_chain()` (`pg_get_functiondef`) must hash exactly `prev_hash` and then
    `HASHED_FIELDS`, in order, each framed by `audit_field`, and nothing else. Any shape the
    reader does not know is a finding (fail closed): a comment, a second digest, a term that is
    not a framed column, a use of NEW outside the framed terms, the three columns it sets and its
    one `RETURN NEW`."""
    if not definition:
        return [Finding("fields", "audit_chain() not found")]
    try:
        framed = framed_fields(definition)
    except _Unparsed as exc:
        return [Finding("fields", f"definition not understood: {exc}")]
    expected = ("prev_hash", *HASHED_FIELDS)
    if framed != expected:
        return [Finding("fields", f"{len(framed)} framed {list(framed)} != expected")]
    return []


def framed_fields(definition: str) -> tuple[str, ...]:
    """The columns the definition's one digest frames, in order; `_Unparsed` for any other
    shape."""
    if "--" in definition or "/*" in definition:
        raise _Unparsed("a comment")
    if len(re.findall(r"\bdigest\s*\(", definition, re.IGNORECASE)) != 1:
        raise _Unparsed("not exactly one digest")
    starts = list(_ENTRY_HASH.finditer(definition))
    if len(starts) != 1:
        raise _Unparsed("the entry_hash assignment")
    args, end = _call_arguments(definition, starts[0].end())
    if len(args) != 2 or args[1].strip() != "'sha256'":
        raise _Unparsed("the digest arguments")
    if not _DIGEST_TAIL.match(definition, end):
        raise _Unparsed("the digest encoding")
    columns: list[str] = []
    for number, raw in enumerate(_split_top_level(args[0], "||"), start=1):
        term = raw.strip()
        plain = _PLAIN_TERM.fullmatch(term)
        if plain is not None and plain.group(1) != "event_ts":
            columns.append(plain.group(1))
        elif _EVENT_TS_TERM.fullmatch(term):
            columns.append("event_ts")
        else:
            raise _Unparsed(f"term {number} is not a framed column")
    sets = [m.group(1) for m in _SETS.finditer(definition)]
    if sorted(sets) not in (["entry_hash", "prev_hash"], ["entry_hash", "id", "prev_hash"]):
        raise _Unparsed("the columns it sets")
    returns = len(_RETURN_NEW.findall(definition))
    if returns != 1 or len(_NEW.findall(definition)) != len(columns) + len(sets) + returns:
        raise _Unparsed("NEW used outside the framed terms")
    return tuple(columns)


def _scan(text: str, start: int) -> Iterator[tuple[int, int]]:
    """(index, paren depth) of each character of `text` from `start` outside a quoted literal
    or identifier, the depth before the character."""
    depth, index, quote = 0, start, ""
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        else:
            yield index, depth
            depth += (char == "(") - (char == ")")
        index += 1
    if quote:
        raise _Unparsed("an unterminated literal")


def _call_arguments(text: str, start: int) -> tuple[list[str], int]:
    """The top-level arguments of the call whose `(` ends just before `start`, and the index
    after its `)`."""
    args: list[str] = []
    begin = start
    for index, depth in _scan(text, start):
        char = text[index]
        if depth == 0 and char == ",":
            args.append(text[begin:index])
            begin = index + 1
        elif depth == 0 and char == ")":
            args.append(text[begin:index])
            return args, index + 1
    raise _Unparsed("an unclosed call")


def _split_top_level(text: str, operator: str) -> list[str]:
    """`text` split at each `operator` outside parentheses and quotes."""
    parts: list[str] = []
    begin = depth = 0
    for index, before in _scan(text, 0):
        if before < 0:
            raise _Unparsed("unbalanced parentheses")
        if before == 0 and index >= begin and text.startswith(operator, index):
            parts.append(text[begin:index])
            begin = index + len(operator)
        depth = before + (text[index] == "(") - (text[index] == ")")
    if depth != 0:
        raise _Unparsed("unbalanced parentheses")
    parts.append(text[begin:])
    return parts


def parse_heads(data: bytes) -> tuple[list[FileHead], list[Finding]]:
    """JSON lines of `head_id` and `head_hash`; any other line is a finding, never skipped."""
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
        if type(head_id) is int and 0 < head_id <= _BIGINT_MAX and isinstance(head_hash, str):
            if _SHA256.fullmatch(head_hash):
                heads.append(FileHead(head_id, head_hash))
                continue
        problems.append(Finding("checkpoint-file", f"line {number}: not a checkpoint head"))
    return heads, problems


async def compare_heads(
    repository: AuditRepository, heads: Sequence[FileHead], head_id: int
) -> list[Finding]:
    """Each file head against the `entry_hash` the walk up to `head_id` just authenticated, with
    `_check_range`'s kinds; above `head_id`, a later append if its hash holds, else truncated."""
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
        shown = "absent" if stored is None else "not a hash"
        shown = stored if stored is not None and _SHA256.fullmatch(stored) else shown
        detail = f"first_bad_id={head.head_id} kind={kind} (file {head.head_hash}, chain {shown})"
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


class SeededStores:
    """`--self-test`: an in-memory `VerifyStores` over a seeded chain (and the unit tests')."""

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
        self.present = {(n, t): (True, shape) for n, (t, shape) in EXPECTED_TRIGGERS.items()}
        self.replication = [("session", "origin")]
        self.definition = RENDERED_CHAIN
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
    async def triggers(self, tables: list[str]) -> dict[tuple[str, str], tuple[bool, str]]:
        return dict(self.present)

    @audit_exempt("read")
    async def replication_roles(self) -> list[tuple[str, str]]:
        return list(self.replication)

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


#: `audit_chain()` as `pg_get_functiondef` renders the definition 0045 deploys: the header
#: rewritten, the body verbatim.
RENDERED_CHAIN: Final = """CREATE OR REPLACE FUNCTION public.audit_chain()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE last_hash sha256_hex;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('audit_log'));
  NEW.id := nextval('audit_log_id_seq');
  SELECT entry_hash INTO last_hash FROM audit_log ORDER BY id DESC LIMIT 1;
  NEW.prev_hash := COALESCE(last_hash, repeat('0',64));
  NEW.entry_hash := encode(digest(
      audit_field(NEW.prev_hash)
      || audit_field(NEW.actor_user_id::text) || audit_field(NEW.actor_label)
      || audit_field(NEW.actor_ip::text) || audit_field(NEW.session_id::text)
      || audit_field(NEW.action) || audit_field(NEW.object_kind)
      || audit_field(NEW.object_id) || audit_field(NEW.outcome::text)
      || audit_field(NEW.severity::text) || audit_field(NEW.reason)
      || audit_field(NEW.before_state::text) || audit_field(NEW.after_state::text)
      || audit_field(NEW.request_id::text) || audit_field(NEW.env::text)
      || audit_field(to_char(NEW.event_ts AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.USOF')),
    'sha256'), 'hex');
  RETURN NEW;
END $function$
"""
_OFF: Final = (False, EXPECTED_TRIGGERS["trg_audit_append"][1])
_UNFRAMED: Final = RENDERED_CHAIN.replace("audit_field(NEW.reason)", "NEW.reason")
_REORDERED: Final = RENDERED_CHAIN.replace(
    "audit_field(NEW.action) || audit_field(NEW.object_kind)",
    "audit_field(NEW.object_kind) || audit_field(NEW.action)",
)


def _file(*heads: tuple[int, str]) -> bytes:
    return "".join(json.dumps({"head_id": h, "head_hash": hh}) + "\n" for h, hh in heads).encode()


async def self_test() -> int:
    """Seeded checks: the clean chain passes; each named injected fault must give its exit code."""
    widened = {("cv_ro", "audit_log"): frozenset(TABLE_PRIVILEGES)}
    append = ("trg_audit_append", "audit_log")
    cases: list[tuple[str, Callable[[SeededStores], Any], int]] = [
        ("clean chain", lambda s: None, EXIT_PASS),
        ("changed entry", lambda s: _replace(s, 4, 14, '{"n": 5}'), EXIT_FAIL),
        ("dropped entry", lambda s: s.rows.pop(3), EXIT_FAIL),
        ("re-ordered entries", lambda s: _swap(s, 2, 3), EXIT_FAIL),
        ("checkpoint above the head", lambda s: s.checkpoints.append((99, "a" * 64)), EXIT_FAIL),
        ("widened grant", lambda s: s.held.update(widened), EXIT_FAIL),
        ("disabled guard", lambda s: s.present.update({append: _OFF}), EXIT_FAIL),
        ("replica default", lambda s: s.replication.append(("session", "replica")), EXIT_FAIL),
        ("no chain function", lambda s: setattr(s, "definition", ""), EXIT_FAIL),
        ("field order", lambda s: setattr(s, "definition", _REORDERED), EXIT_FAIL),
        ("unframed field", lambda s: setattr(s, "definition", _UNFRAMED), EXIT_FAIL),
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
