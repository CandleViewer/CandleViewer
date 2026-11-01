"""Postgres `RuleStore` adapter for `RulesManager` (E35-S01; tables from `0013_rules`).

Composition-root helper (like `health_wiring`): `rules` (M15) may not import `storage` (M10)
and vice versa, so only this wiring module sees both. Static, parameterised SQL.

Mapping: one `rules` row per `RuleRow`; one immutable `rule_versions` row per `VersionRow`
(`UNIQUE (rule_id, version)` is the database-level optimistic-concurrency backstop and
`UNIQUE (rule_id, ir_hash)` the dedupe guarantee). Simulation evidence has no column of
its own: it is stored per version in `rule_versions.backtest_summary`
(`{"simulated": true, "fires": n, "hours": h}`), so "simulated on this exact ir_hash" is
provable from the version row. `rules.armed_at/armed_by` satisfy `rule_armed_shape`.

`PostgresArmedRules` binds the accounts port `ArmedRules` (#906 ruling B6, #4563): the armed rules
that block deleting a profile of an account, every rule whose active version's scope lists the
account or lists none (24 §9.2). `rules.scope` and `rules.scope_account_id` are not read: they keep
the first version's level and first account only.

SR-051 (the scope is part of the query): every read that answers a caller takes its
`RuleReadScope` inside the statement, never as a filter after the fetch. Each read is a pair of
static statements that differ only in their scope predicate (unit-pinned): the Owner role's binds
the caller to a live owner role (`_OWNER_PRED`, the accounts store's own); anyone else's reads only
the caller's own rules whose every version's `account_refs` lies within the request's grants. A
version's `account_refs` is the set the generic walker (`collect_account_ids`) reads from its IR,
the walker `RulesManager._visible` reads, written with the version; a version stored before the
column existed holds NULL, which no grant scope admits until the fill writes it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Sequence
from typing import Any, Final

import sqlalchemy as sa
import structlog

from candleviewer.accounts.profile_repository import ARMED_SHOWN, ArmedRule
from candleviewer.rules.ir.accounts import collect_account_ids
from candleviewer.rules.manager import GrantRead, OwnerRead, RuleReadScope, RuleRow, VersionRow
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: How many versions one step of the fill reads and writes.
FILL_BATCH: Final = 500

_SELECT_RULE = sa.text(
    "SELECT id::text AS id, name, owner_user_id::text AS owner, scope::text AS scope, "
    "mode::text AS mode, active_version_id::text AS active_version_id, "
    "armed_by::text AS armed_by, disabled_reason, deleted_at IS NOT NULL AS deleted, "
    "last_edit_session_id AS last_session, updated_by::text AS last_editor FROM rules "
    "WHERE id = CAST(:id AS uuid)"
)
_SELECT_RULES = sa.text(
    "SELECT id::text AS id, name, owner_user_id::text AS owner, scope::text AS scope, "
    "mode::text AS mode, active_version_id::text AS active_version_id, "
    "armed_by::text AS armed_by, disabled_reason, deleted_at IS NOT NULL AS deleted, "
    "last_edit_session_id AS last_session, updated_by::text AS last_editor FROM rules"
)
_SELECT_VERSIONS_OF = sa.text(
    "SELECT id::text AS id, rule_id::text AS rule_id, version, ir, ir_hash::text AS ir_hash, "
    "compiler_version, notes, created_by::text AS author, backtest_summary AS sim "
    "FROM rule_versions WHERE rule_id = CAST(:id AS uuid)"
)
_SELECT_VERSIONS = sa.text(
    "SELECT id::text AS id, rule_id::text AS rule_id, version, ir, ir_hash::text AS ir_hash, "
    "compiler_version, notes, created_by::text AS author, backtest_summary AS sim "
    "FROM rule_versions"
)
_LOCK = sa.text("SELECT 1 FROM rules WHERE id = CAST(:id AS uuid) FOR UPDATE")
_UPSERT_RULE = sa.text(
    "INSERT INTO rules (id, name, owner_user_id, scope, scope_account_id, scope_symbol, mode, "
    "armed_at, armed_by, deleted_at, created_by, updated_by) "
    "VALUES (CAST(:id AS uuid), :name, CAST(:owner AS uuid), CAST(:scope AS rule_scope), "
    "CAST(:acct AS uuid), :sym, 'disabled', NULL, NULL, NULL, CAST(:owner AS uuid), "
    "CAST(:owner AS uuid)) ON CONFLICT (id) DO NOTHING"
)
_INSERT_VERSION = sa.text(
    "INSERT INTO rule_versions (id, rule_id, version, ir, ir_hash, compiler_version, notes, "
    "is_valid, created_by, account_refs) VALUES (CAST(:id AS uuid), CAST(:rule_id AS uuid), "
    ":version, CAST(:ir AS jsonb), :ir_hash, :compiler_version, :notes, true, "
    "CAST(:author AS uuid), CAST(:refs AS text[])) ON CONFLICT (id) DO NOTHING"
)
_SET_SIM = sa.text(
    "UPDATE rule_versions SET backtest_summary = CAST(:sim AS jsonb) WHERE id = CAST(:id AS uuid)"
)
_UPDATE_RULE = sa.text(
    "UPDATE rules SET name = :name, mode = CAST(:mode AS rule_mode), "
    "active_version_id = CAST(:active AS uuid), disabled_reason = :disabled_reason, "
    "armed_at = CASE WHEN :mode = 'armed' THEN COALESCE(armed_at, now()) ELSE NULL END, "
    "armed_by = CASE WHEN :mode = 'armed' THEN CAST(:armed_by AS uuid) ELSE NULL END, "
    "deleted_at = CASE WHEN :deleted THEN COALESCE(deleted_at, now()) ELSE NULL END, "
    "last_edit_session_id = COALESCE(NULLIF(:sess, ''), last_edit_session_id), "
    "last_edit_at = CASE WHEN :sess <> '' THEN now() ELSE last_edit_at END, "
    "updated_by = COALESCE(CAST(NULLIF(:editor, '') AS uuid), updated_by), "
    "updated_at = now() WHERE id = CAST(:id AS uuid)"
)

#: SR-051, the Owner role's read: the caller holds a live owner role, checked inside the statement,
#: so an Owner scope handed to anyone else reads no row. Verbatim the accounts store's predicate
#: (`accounts_sqlalchemy._OWNER_PRED`, unit-pinned equal); its `r` names `roles`, so `rules` is
#: `rl` in every scoped statement.
_OWNER_PRED: Final = (
    "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "JOIN users u ON u.id = ur.user_id WHERE ur.user_id = CAST(:caller AS uuid) "
    "AND r.name = 'owner' AND u.deleted_at IS NULL AND u.status = 'active' "
    "AND (ur.expires_at IS NULL OR ur.expires_at > now()))"
)
#: Ownership alone: what the name lookup reads for anyone but the Owner role (G-14).
_OWN_PRED: Final = "rl.owner_user_id = CAST(:caller AS uuid)"
#: Anyone else's read: `_OWN_PRED` (unit-pinned as its head), with no version naming an account
#: outside the grants and no version whose account set is not computed yet (NULL is outside).
_GRANT_PRED: Final = (
    "rl.owner_user_id = CAST(:caller AS uuid) AND NOT EXISTS (SELECT 1 FROM rule_versions v "
    "WHERE v.rule_id = rl.id "
    "AND (v.account_refs IS NULL OR NOT v.account_refs <@ CAST(:granted AS text[])))"
)
_PAGE_HEAD: Final = (
    "SELECT rl.id::text AS id, rl.name AS name, rl.owner_user_id::text AS owner, "
    "rl.scope::text AS scope, rl.mode::text AS mode, "
    "rl.active_version_id::text AS active_version_id, rl.armed_by::text AS armed_by, "
    "rl.disabled_reason AS disabled_reason, rl.deleted_at IS NOT NULL AS deleted, "
    "rl.last_edit_session_id AS last_session, rl.updated_by::text AS last_editor "
    "FROM rules rl WHERE rl.deleted_at IS NULL AND "
)
#: The filters, the keyset on the primary key, the point read's one id and the bound: bound
#: values only, so the statement text never varies.
_PAGE_TAIL: Final = (
    " AND (CAST(:mode AS text) IS NULL OR rl.mode::text = CAST(:mode AS text))"
    " AND (CAST(:level AS text) IS NULL OR rl.scope::text = CAST(:level AS text))"
    " AND (CAST(:after AS uuid) IS NULL OR rl.id > CAST(:after AS uuid))"
    " AND (CAST(:only AS uuid) IS NULL OR rl.id = CAST(:only AS uuid))"
    " ORDER BY rl.id LIMIT :limit"
)
_PAGE_OWNER: Final = sa.text(_PAGE_HEAD + _OWNER_PRED + _PAGE_TAIL)
_PAGE_GRANT: Final = sa.text(_PAGE_HEAD + _GRANT_PRED + _PAGE_TAIL)
_IDS_HEAD: Final = "SELECT rl.id::text AS id FROM rules rl WHERE rl.deleted_at IS NULL AND "
_IDS_OWNER: Final = sa.text(_IDS_HEAD + _OWNER_PRED + " ORDER BY rl.id")
_IDS_GRANT: Final = sa.text(_IDS_HEAD + _GRANT_PRED + " ORDER BY rl.id")
#: The save's name check (G-14): the exact name among live rules, the edited rule excluded.
_NAME_HEAD: Final = (
    "SELECT EXISTS (SELECT 1 FROM rules rl WHERE rl.deleted_at IS NULL AND rl.name = :name "
    "AND (CAST(:exclude AS uuid) IS NULL OR rl.id <> CAST(:exclude AS uuid)) AND "
)
_NAME_OWNER: Final = sa.text(_NAME_HEAD + _OWNER_PRED + ")")
_NAME_OWN: Final = sa.text(_NAME_HEAD + _OWN_PRED + ")")
#: The versions of one scoped page, by the page's rule ids.
_VERSIONS_OF_PAGE: Final = sa.text(
    "SELECT id::text AS id, rule_id::text AS rule_id, version, ir, ir_hash::text AS ir_hash, "
    "compiler_version, notes, created_by::text AS author, backtest_summary AS sim "
    "FROM rule_versions WHERE rule_id = ANY(CAST(:ids AS uuid[]))"
)
#: The fill: versions stored before `account_refs` existed, a batch at a time, each written once.
_UNFILLED: Final = sa.text(
    "SELECT id::text AS id, ir FROM rule_versions WHERE account_refs IS NULL ORDER BY id LIMIT :n"
)
_FILL: Final = sa.text(
    "UPDATE rule_versions SET account_refs = CAST(:refs AS text[]) "
    "WHERE id = CAST(:id AS uuid) AND account_refs IS NULL"
)

# A rule covers an account when its ACTIVE version's `scope.account_ids` lists it or is empty
# (`ScopeResolver.resolve`: no list means every granted account), whatever `scope.level`. A list
# that is missing or not an array covers every account too, as does an element that is not a
# readable account id (not a string, or not a UUID): fail closed. `CASE`, not `OR`: Postgres
# does not short-circuit `OR`, and `jsonb_array_length` raises on a non-array, as the `::uuid`
# cast does on an unreadable element. `pg_input_is_valid` is Postgres 16+ (CI runs 16.4).
_ARMED_ON = sa.text(
    "SELECT r.id::text AS id, r.name FROM rules r "
    "JOIN rule_versions v ON v.id = r.active_version_id "
    "WHERE r.mode = 'armed' AND r.deleted_at IS NULL AND CASE "
    "WHEN jsonb_typeof(v.ir #> '{scope,account_ids}') = 'array' "
    "THEN jsonb_array_length(v.ir #> '{scope,account_ids}') = 0 OR EXISTS ("
    "SELECT 1 FROM jsonb_array_elements(v.ir #> '{scope,account_ids}') AS a(el) "
    "WHERE CASE WHEN jsonb_typeof(a.el) = 'string' AND pg_input_is_valid(a.el #>> '{}', 'uuid') "
    "THEN (a.el #>> '{}')::uuid = CAST(:account AS uuid) ELSE true END) "
    "ELSE true END "
    "ORDER BY lower(r.name), r.id LIMIT :limit"
)

#: Every statement of this module by what it serves (unit-pinned, the accounts store's way): the
#: Owner role's scoped reads, anyone else's, and the rest, which answer no caller's view (the
#: writes, the reads by id or whole that writes and the evaluator take, a scoped page's versions,
#: the fill and `PostgresArmedRules`).
OWNER_STATEMENTS: Final = frozenset({_PAGE_OWNER, _IDS_OWNER, _NAME_OWNER})
GRANT_STATEMENTS: Final = frozenset({_PAGE_GRANT, _IDS_GRANT, _NAME_OWN})
UNSCOPED_STATEMENTS: Final = frozenset(
    {
        _SELECT_RULE, _SELECT_RULES, _SELECT_VERSIONS_OF, _SELECT_VERSIONS, _LOCK, _UPSERT_RULE,
        _INSERT_VERSION, _SET_SIM, _UPDATE_RULE, _VERSIONS_OF_PAGE, _UNFILLED, _FILL, _ARMED_ON,
    }
)  # fmt: skip


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _ir_of(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else json.loads(raw)


class PostgresRuleStore:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational
        #: The fill runs once per process before the first grant-scoped read, one at a time.
        self._filling = asyncio.Lock()
        self._filled = False

    @staticmethod
    def _assemble(rules: Sequence[Any], versions: Sequence[Any]) -> list[RuleRow]:
        by_rule: dict[str, list[VersionRow]] = {}
        sims: dict[str, tuple[set[str], int, float]] = {}
        for v in sorted(versions, key=lambda r: (r.rule_id, r.version)):
            ir = _ir_of(v.ir)
            by_rule.setdefault(v.rule_id, []).append(
                VersionRow(
                    v.id,
                    v.rule_id,
                    int(v.version),
                    ir,
                    v.ir_hash,
                    v.compiler_version,
                    v.notes,
                    v.author or "",
                    "",
                )
            )
            sim = v.sim if isinstance(v.sim, dict) else None
            if sim and sim.get("simulated"):
                hashes, _, _ = sims.get(v.rule_id, (set(), 0, 0.0))
                hashes.add(v.ir_hash)
                sims[v.rule_id] = (hashes, int(sim.get("fires", 0)), float(sim.get("hours", 0.0)))
        out: list[RuleRow] = []
        for r in rules:
            vs = by_rule.get(r.id, [])
            hashes, fires, hours = sims.get(r.id, (set(), 0, 0.0))
            out.append(
                RuleRow(
                    id=r.id,
                    name=r.name,
                    owner=r.owner,
                    mode=r.mode,
                    scope=r.scope,
                    active_version_id=r.active_version_id,
                    latest_version=vs[-1].version if vs else 0,
                    last_editor=r.last_editor or (vs[-1].author if vs else ""),
                    last_session=r.last_session or "",
                    deleted=bool(r.deleted),
                    simulated_hashes=hashes,
                    simulation_fires=fires,
                    simulation_hours=hours,
                    versions=vs,
                    armed_by=r.armed_by,
                    disabled_reason=r.disabled_reason,
                )
            )
        return out

    async def get(self, rule_id: str) -> RuleRow | None:
        try:
            uuid.UUID(rule_id)
        except ValueError:
            return None
        async with self._relational.unit_of_work() as uow:
            rules = (await uow.session.execute(_SELECT_RULE, {"id": rule_id})).all()
            vers = (await uow.session.execute(_SELECT_VERSIONS_OF, {"id": rule_id})).all()
        rows = self._assemble(rules, vers)
        return rows[0] if rows else None

    async def all(self) -> list[RuleRow]:
        async with self._relational.unit_of_work() as uow:
            rules = (await uow.session.execute(_SELECT_RULES)).all()
            vers = (await uow.session.execute(_SELECT_VERSIONS)).all()
        return self._assemble(rules, vers)

    @staticmethod
    def _scoped(
        scope: RuleReadScope, owner: sa.TextClause, grant: sa.TextClause
    ) -> tuple[sa.TextClause, dict[str, Any]]:
        """The SR-051 variant of a read for `scope`, with the scope's bound values: which statement
        runs decides the role, never a bound flag."""
        if isinstance(scope, OwnerRead):
            return owner, {"caller": scope.user_id}
        return grant, {"caller": scope.user_id, "granted": sorted(scope.granted)}

    async def scoped_page(
        self,
        scope: RuleReadScope,
        *,
        mode: str | None,
        level: str | None,
        after: str | None,
        limit: int,
        only: str | None = None,
    ) -> list[RuleRow]:
        """At most `limit` live rows in `scope`, by id, after `after` or the one id `only`, with
        their versions. A cursor that is not a UUID is a `ValueError` before any statement (the
        route answers it first); a scope whose user id is not a UUID, or an `only` that is not
        one, names no row and runs no statement."""
        if after is not None and not _is_uuid(after):
            raise ValueError("cursor is not a rule id")
        if limit < 1:
            raise ValueError("limit must be positive")
        if not _is_uuid(scope.user_id) or (only is not None and not _is_uuid(only)):
            return []
        if isinstance(scope, GrantRead):
            await self._fill_account_refs()
        stmt, params = self._scoped(scope, _PAGE_OWNER, _PAGE_GRANT)
        params |= {"mode": mode, "level": level, "after": after, "only": only, "limit": limit}
        async with self._relational.unit_of_work() as uow:
            rules = (await uow.session.execute(stmt, params)).all()
            ids = [r.id for r in rules]
            vers = (await uow.session.execute(_VERSIONS_OF_PAGE, {"ids": ids})).all() if ids else []
        return self._assemble(rules, vers)

    async def scoped_ids(self, scope: RuleReadScope) -> frozenset[str]:
        """The ids of the live rules in `scope`, ids only."""
        if not _is_uuid(scope.user_id):
            return frozenset()
        if isinstance(scope, GrantRead):
            await self._fill_account_refs()
        stmt, params = self._scoped(scope, _IDS_OWNER, _IDS_GRANT)
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(stmt, params)).all()
        return frozenset(r.id for r in rows)

    async def name_taken(self, scope: RuleReadScope, name: str, exclude: str) -> bool:
        """Whether a live rule other than `exclude` holds exactly `name`: any for the Owner role,
        the caller's own for anyone else, readable or not (G-14). Ownership alone decides, so this
        lookup needs no account set and no fill."""
        if not _is_uuid(scope.user_id):
            return False
        stmt = _NAME_OWNER if isinstance(scope, OwnerRead) else _NAME_OWN
        params = {
            "caller": scope.user_id,
            "name": name,
            "exclude": exclude if _is_uuid(exclude) else None,
        }
        async with self._relational.unit_of_work() as uow:
            return bool((await uow.session.execute(stmt, params)).scalar_one())

    async def _fill_account_refs(self) -> None:
        """Write `account_refs` for every version that holds none, from its stored IR with the
        walker, a batch at a time and only where it is still NULL; done once a batch finds none.
        A failed fill is logged (counts only) and tried again on the next grant-scoped read; the
        versions it left hold NULL, outside every grant scope, and the read itself runs."""
        if self._filled:
            return
        async with self._filling:
            if self._filled:
                return
            filled = 0
            try:
                while written := await self._fill_batch():
                    filled += written
            except Exception as lost:  # logged; the read narrows, never fails
                _log().error(
                    "rules.account_refs_fill_failed", filled=filled, error=type(lost).__name__
                )
                return
            self._filled = True

    async def _fill_batch(self) -> int:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_UNFILLED, {"n": FILL_BATCH})).all()
            for r in rows:
                refs = sorted(set(collect_account_ids(_ir_of(r.ir))))
                await uow.session.execute(_FILL, {"id": r.id, "refs": refs})
            await uow.commit()
        return len(rows)

    async def put(self, row: RuleRow) -> None:
        first = row.versions[0].ir.get("scope", {}) if row.versions else {}
        accts = first.get("account_ids") or []
        syms = first.get("symbols") or []
        async with self._relational.unit_of_work() as uow:
            s = uow.session
            await s.execute(
                _UPSERT_RULE,
                {
                    "id": row.id,
                    "name": row.name,
                    "owner": row.owner,
                    "scope": row.scope,
                    "acct": str(accts[0]) if accts else None,
                    "sym": str(syms[0]) if syms else None,
                },
            )
            await s.execute(_LOCK, {"id": row.id})  # serialise writers per rule
            for v in row.versions:  # immutable: existing ids are left untouched
                await s.execute(
                    _INSERT_VERSION,
                    {
                        "id": v.id,
                        "rule_id": row.id,
                        "version": v.version,
                        "ir": json.dumps(v.ir, sort_keys=True),
                        "ir_hash": v.ir_hash,
                        "compiler_version": v.compiler_version,
                        "notes": v.notes,
                        "author": v.author or None,
                        # SR-051: the accounts the version names, as `_visible` reads them.
                        "refs": sorted(set(collect_account_ids(v.ir))),
                    },
                )
                if v.ir_hash in row.simulated_hashes:
                    sim = {
                        "simulated": True,
                        "fires": row.simulation_fires,
                        "hours": row.simulation_hours,
                    }
                    await s.execute(_SET_SIM, {"id": v.id, "sim": json.dumps(sim)})
            await s.execute(
                _UPDATE_RULE,
                {
                    "id": row.id,
                    "name": row.name,
                    "mode": row.mode,
                    "active": row.active_version_id,
                    "armed_by": row.armed_by or row.owner,
                    "deleted": row.deleted,
                    "disabled_reason": row.disabled_reason,
                    "sess": row.last_session,
                    "editor": row.last_editor,
                },
            )
            await uow.commit()


class PostgresArmedRules:
    """`ArmedRules` over `rules` and their active `rule_versions`: the live armed rules that cover
    an account (its active version's `scope.account_ids` lists it, is empty, or is missing or
    unreadable), one more than a refused delete names, so it can say that there are more.

    Strict on protected `sys.*` rules: one armed with no account list would block every profile
    delete until it is disarmed (none is today); it is not excluded, so a delete never goes
    through under a rule that covers the account."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def armed_on(self, account_id: uuid.UUID) -> tuple[ArmedRule, ...]:
        return await self.covering(account_id, limit=ARMED_SHOWN + 1)

    async def covering(self, account_id: uuid.UUID, *, limit: int) -> tuple[ArmedRule, ...]:
        """The armed rules covering the account under `_ARMED_ON`, at most `limit`: the one
        predicate the profile delete's guard and the consequence read share (#898 ruling 10)."""
        if limit < 1:
            raise ValueError("limit must be positive")
        params = {"account": str(account_id), "limit": limit}
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_ARMED_ON, params)).all()
        return tuple(ArmedRule(uuid.UUID(row.id), row.name) for row in rows)


__all__ = ["PostgresArmedRules", "PostgresRuleStore"]
