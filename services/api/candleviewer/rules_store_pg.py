"""Postgres `RuleStore` adapter for `RulesManager` (E35-S01; tables from `0013_rules`).

Composition-root helper (like `health_wiring`): `rules` (M15) may not import `storage` (M10)
and vice versa, so only this wiring module sees both. Static, parameterised SQL.

Mapping: one `rules` row per `RuleRow`; one immutable `rule_versions` row per `VersionRow`
(`UNIQUE (rule_id, version)` is the database-level optimistic-concurrency backstop and
`UNIQUE (rule_id, ir_hash)` the dedupe guarantee). Simulation evidence has no column of
its own: it is stored per version in `rule_versions.backtest_summary`
(`{"simulated": true, "fires": n, "hours": h}`), so "simulated on this exact ir_hash" is
provable from the version row. `rules.armed_at/armed_by` satisfy `rule_armed_shape`.

`PostgresArmedRules` binds the accounts port `ArmedRules` (#906 ruling B6): the armed rules that
block deleting a profile of an account, read through `ix_rules_account`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from candleviewer.accounts.profile_repository import ARMED_SHOWN, ArmedRule
from candleviewer.rules.manager import RuleRow, VersionRow
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

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
    "is_valid, created_by) VALUES (CAST(:id AS uuid), CAST(:rule_id AS uuid), :version, "
    "CAST(:ir AS jsonb), :ir_hash, :compiler_version, :notes, true, CAST(:author AS uuid)) "
    "ON CONFLICT (id) DO NOTHING"
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

_ARMED_ON = sa.text(
    "SELECT id::text AS id, name FROM rules WHERE scope = 'account' "
    "AND scope_account_id = CAST(:account AS uuid) AND mode = 'armed' AND deleted_at IS NULL "
    "ORDER BY lower(name), id LIMIT :limit"
)


def _ir_of(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else json.loads(raw)


class PostgresRuleStore:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

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
    """`ArmedRules` over the `rules` table: an account's live armed rules, one more than a refused
    delete names, so it can say that there are more."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def armed_on(self, account_id: uuid.UUID) -> tuple[ArmedRule, ...]:
        params = {"account": str(account_id), "limit": ARMED_SHOWN + 1}
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_ARMED_ON, params)).all()
        return tuple(ArmedRule(uuid.UUID(row.id), row.name) for row in rows)


__all__ = ["PostgresArmedRules", "PostgresRuleStore"]
