"""Offline audit-integrity checks: the chain, the grant model and the off-box mirror (E43-T10).

Pure functions over rows and catalogue facts that a caller has already read; no I/O, no driver.
`candleviewer.admin.audit_chain_verify` reads them read-only from Postgres and prints the result.

* The chain (SR-063): every row's `prev_hash` must be the `entry_hash` of the row before it (the
  first row's, 64 zeros), and its hashed fields must recompute to its `entry_hash` with the one
  canonical encoder, `audit_chain()`'s mirror in `candleviewer.audit.query`. A changed row fails its
  own hash; a dropped row, or two rows whose contents were swapped, fail the link of the row after
  the gap. Ids must rise strictly. The walk stops at the first break and names its id.
* The grant model (C-5.7, US-ADMIN-008): `cv_app` holds exactly SELECT and INSERT on each audit
  table, `cv_ro` exactly SELECT (`infra/scripts/pg_bootstrap.sql` default privileges less the
  REVOKE of `0003_audit_log`), and the guard triggers of `0003_audit_log` are present and enabled.
* The mirror (SR-068): every head the off-box file records (the checkpoint job's JSON lines) must
  name an entry of the local chain with the same hash; a head above the local head means the local
  tail is gone. Database checkpoints are compared the same way.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from candleviewer.audit.query import _canonical_digest  # the one encoder (SR-063)
from candleviewer.audit.repository import HASHED_FIELDS

GENESIS: Final = "0" * 64
AUDIT_TABLES: Final = ("audit_log", "audit_checkpoints")
APP_ROLES: Final = ("cv_app", "cv_ro")
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
#: The privileges the 0003 migration revokes from both roles on both tables.
REVOKED: Final = frozenset({"UPDATE", "DELETE", "TRUNCATE"})
EXPECTED_GRANTS: Final[Mapping[tuple[str, str], frozenset[str]]] = {
    ("cv_app", "audit_log"): frozenset({"SELECT", "INSERT"}),
    ("cv_app", "audit_checkpoints"): frozenset({"SELECT", "INSERT"}),
    ("cv_ro", "audit_log"): frozenset({"SELECT"}),
    ("cv_ro", "audit_checkpoints"): frozenset({"SELECT"}),
}
#: Trigger name -> table, as `0003_audit_log` creates them.
EXPECTED_TRIGGERS: Final[Mapping[str, str]] = {
    "trg_audit_chain": "audit_log",
    "trg_audit_append": "audit_log",
    "trg_audit_no_truncate": "audit_log",
    "trg_audit_ckpt_append": "audit_checkpoints",
    "trg_audit_ckpt_no_truncate": "audit_checkpoints",
}
_HEX64: Final = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class Finding:
    """One failed check. `code` is stable; `detail` names ids, hashes, roles and privileges only,
    never a payload field or a connection string."""

    code: str
    detail: str

    def line(self) -> str:
        return f"FAIL {self.code}: {self.detail}"


@dataclass(slots=True)
class ChainWalker:
    """Walks rows `(id, prev_hash, entry_hash, *renderings)` fed in id order, batch by batch.
    `watch` holds ids whose `entry_hash` the mirror and checkpoint comparisons need."""

    watch: frozenset[int] = frozenset()
    checked: int = 0
    head_id: int = 0
    head_hash: str = GENESIS
    first_break: Finding | None = None
    seen: dict[int, str] = field(default_factory=dict)

    @property
    def broken(self) -> bool:
        return self.first_break is not None

    def feed(self, rows: Iterable[Sequence[object]]) -> bool:
        """Check `rows`; return False once a break is found (the walk stops there)."""
        for row in rows:
            if self.first_break is not None:
                return False
            entry_id, prev_hash, entry_hash = int(str(row[0])), row[1], row[2]
            self.checked += 1
            if entry_id <= self.head_id:
                return self._break("chain_id_order", entry_id, f"follows id {self.head_id}")
            if prev_hash != self.head_hash:
                return self._break("chain_prev_hash_mismatch", entry_id, "link to predecessor")
            renderings = [None if v is None else str(v) for v in row[3:]]
            if len(renderings) != len(HASHED_FIELDS):
                return self._break("chain_row_shape", entry_id, f"{len(renderings)} fields")
            if _canonical_digest(self.head_hash, renderings) != entry_hash:
                return self._break("chain_entry_hash_mismatch", entry_id, "content altered")
            self.head_id, self.head_hash = entry_id, str(entry_hash)
            if entry_id in self.watch:
                self.seen[entry_id] = self.head_hash
        return self.first_break is None

    def _break(self, code: str, entry_id: int, why: str) -> bool:
        self.first_break = Finding(code, f"chain breaks at id {entry_id} ({why})")
        return False


@dataclass(frozen=True, slots=True)
class MirrorHead:
    head_id: int
    head_hash: str


def parse_mirror(text: str) -> tuple[list[MirrorHead], list[Finding]]:
    """The checkpoint job's off-box JSON lines (`audit.checkpoint`): each a `head_id` and a
    `head_hash`. A line that is not one is a finding, never skipped."""
    heads: list[MirrorHead] = []
    problems: list[Finding] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            record = None
        head_id = record.get("head_id") if isinstance(record, dict) else None
        head_hash = record.get("head_hash") if isinstance(record, dict) else None
        if (
            type(head_id) is not int
            or head_id < 1
            or not isinstance(head_hash, str)
            or not _HEX64.fullmatch(head_hash)
        ):
            problems.append(Finding("mirror_line_invalid", f"line {number}"))
            continue
        heads.append(MirrorHead(head_id, head_hash))
    return heads, problems


def mirror_digest(data: bytes) -> str:
    """The sha256 of the mirror file's bytes, the value the off-box target records."""
    return hashlib.sha256(data).hexdigest()


def compare_heads(source: str, heads: Iterable[MirrorHead], walker: ChainWalker) -> list[Finding]:
    """Each recorded head against the walked chain. Run only after a walk with no break: the
    walk's `seen` then holds every watched id the chain has, up to `walker.head_id`."""
    findings: list[Finding] = []
    for head in heads:
        local = walker.seen.get(head.head_id)
        if head.head_id > walker.head_id:
            detail = f"{source} head id {head.head_id} is above the local head id {walker.head_id}"
            findings.append(Finding(f"{source}_ahead_of_local", detail))
        elif local is None:
            detail = f"{source} head id {head.head_id} names no local entry"
            findings.append(Finding(f"{source}_head_missing", detail))
        elif local != head.head_hash:
            detail = f"id {head.head_id}: {source} {head.head_hash} != local {local}"
            findings.append(Finding(f"{source}_divergence", detail))
    return findings


def check_grants(held: Mapping[tuple[str, str], frozenset[str]]) -> list[Finding]:
    """`held` maps (role, table) to the privileges the role holds; a pair with no entry means the
    role or the table is absent. Each pair must hold exactly `EXPECTED_GRANTS`."""
    findings: list[Finding] = []
    for (role, table), expected in sorted(EXPECTED_GRANTS.items()):
        got = held.get((role, table))
        if got is None:
            findings.append(Finding("grant_absent", f"{role} on {table}: role or table missing"))
            continue
        extra, missing = sorted(got - expected), sorted(expected - got)
        if extra or missing:
            detail = f"{role} on {table}: extra {extra or '[]'}, missing {missing or '[]'}"
            findings.append(Finding("grant_mismatch", detail))
    return findings


def check_triggers(present: Mapping[str, tuple[str, bool]]) -> list[Finding]:
    """`present` maps a trigger name to (its table, enabled). Each guard must be on its table
    and enabled."""
    findings: list[Finding] = []
    for name, table in sorted(EXPECTED_TRIGGERS.items()):
        got = present.get(name)
        if got is None or got[0] != table:
            findings.append(Finding("trigger_absent", f"{name} on {table}"))
        elif not got[1]:
            findings.append(Finding("trigger_disabled", f"{name} on {table}"))
    return findings


# --- static consistency with the shipped migrations (`--check`) -------------------------------

_FIELD_REF: Final = re.compile(r"audit_field\(\s*(?:to_char\(\s*)?NEW\.([a-z_]+)")
_REVOKE: Final = re.compile(r"REVOKE ([A-Z, ]+) ON ([a-z_]+) FROM ([a-z_]+)")
_TRIGGER: Final = re.compile(r"CREATE TRIGGER ([a-z_]+)\s+BEFORE [A-Z ]+ ON ([a-z_]+)")


def hashed_field_order(chain_sql: str) -> tuple[str, ...]:
    """The columns `audit_chain()` frames with `audit_field`, in order."""
    return tuple(_FIELD_REF.findall(chain_sql))


def declared_revokes(migration_sql: str) -> dict[tuple[str, str], frozenset[str]]:
    """(role, table) -> privileges a migration's REVOKE statements take away."""
    out: dict[tuple[str, str], frozenset[str]] = {}
    for privileges, table, role in _REVOKE.findall(migration_sql):
        named = frozenset(p.strip() for p in privileges.split(","))
        out[(role, table)] = out.get((role, table), frozenset()) | named
    return out


def declared_triggers(migration_sql: str) -> dict[str, str]:
    return dict(_TRIGGER.findall(migration_sql))


def static_findings(chain_sql: str, audit_migration_sql: str) -> list[Finding]:
    """The tool's expectations against the migrations: the hashed field order of the latest
    `audit_chain()`, the REVOKE set and the guard triggers of `0003_audit_log`."""
    findings: list[Finding] = []
    order = hashed_field_order(chain_sql)
    if order != ("prev_hash", *HASHED_FIELDS):
        findings.append(Finding("static_field_order", f"audit_chain() frames {list(order)}"))
    revokes = declared_revokes(audit_migration_sql)
    for pair, expected in sorted(EXPECTED_GRANTS.items()):
        revoked = revokes.get(pair, frozenset())
        if revoked != REVOKED or revoked & expected:
            findings.append(Finding("static_revokes", f"{pair[0]} on {pair[1]}: {sorted(revoked)}"))
    if declared_triggers(audit_migration_sql) != dict(EXPECTED_TRIGGERS):
        findings.append(Finding("static_triggers", "0003 guard triggers differ"))
    return findings


# --- a seeded chain (`--self-test` and the unit tests) ----------------------------------------


def seed_rows(count: int) -> list[tuple[object, ...]]:
    """A valid chain of `count` synthetic entries, ids with gaps as the real table has."""
    rows: list[tuple[object, ...]] = []
    prev = GENESIS
    for n in range(1, count + 1):
        values: list[str | None] = [
            None,
            f"seed-{n}",
            None,
            None,
            "audit.seed.entry",
            "seed",
            str(n),
            "success",
            "info",
            None,
            None,
            json.dumps({"n": n, "label": "zé"}, ensure_ascii=False),
            None,
            "demo",
            f"2026-11-04T00:00:{n % 60:02d}.{n:06d}+00",
        ]
        entry = _canonical_digest(prev, values)
        rows.append((2 * n, prev, entry, *values))
        prev = entry
    return rows


def walk(rows: Sequence[Sequence[object]], watch: Iterable[int] = ()) -> ChainWalker:
    walker = ChainWalker(watch=frozenset(watch))
    walker.feed(rows)
    return walker
