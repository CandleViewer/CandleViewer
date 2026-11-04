"""Postgres repository for alerts (migration `0014_alerts`, E40-T01).

Lives in M10 (`storage`): only M10 may import a storage driver (ADR-0003) and M10
may not import `candleviewer.alerts` (M22), so this module returns plain frozen
dataclasses. `webhook_url_enc` / `webhook_secret_enc` are SECRET: the read path
selects an explicit column allow-list (`ALERT_COLUMNS`) that never contains them.
Cursor pagination is keyset (opaque base64 of `(ts, id)`), never OFFSET.
Static, parameterised SQL only. Deliveries: `alert_deliveries_sqlalchemy.py`.

Armed-alert cap (#1864): a write that arms an alert (a create with `enabled`, or a replace or
`set_enabled` turning a disarmed alert's `enabled` on) takes the owner's advisory cap lock, then
counts the owner's armed alerts and writes in the same transaction (`armed_breach`), as the
drawings quota does (#2727). A disarm takes no lock and is never refused.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.alerts import (
    MAX_ARMED_ALERTS,
    AlertConflictError,
    AlertNameTakenError,
    AlertRow,
    Page,
    armed_breach,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    SqlAlchemyUnitOfWork,
    constraint_of,
    query_failure,
    sqlstate_of,
)

#: Explicit read allow-list: the SECRET `webhook_*_enc` columns are deliberately absent.
ALERT_COLUMNS = (
    "id::text AS id, owner_user_id::text AS owner_user_id, name, symbol, "
    "scope_account_id::text AS scope_account_id, condition_ir, "
    "condition_hash::text AS condition_hash, enabled, trigger_mode::text AS trigger_mode, "
    "cooldown_seconds, snoozed_until, expires_at, severity::text AS severity, "
    "channels::text[] AS channels, (webhook_url_enc IS NOT NULL) AS has_webhook, "
    "message_template, last_fired_at, fire_count, created_at, updated_at, disarm_reason"
)


#: Mirror of the `alert_channel` enum (migration 0014).
ALERT_CHANNELS = frozenset({"in_app", "email", "webhook", "push", "desktop"})


def encode_cursor(ts: datetime, row_id: int | str) -> str:
    raw = json.dumps([ts.isoformat(), str(row_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """`ValueError` for anything `encode_cursor` cannot have made: malformed, a timestamp without
    an offset or a UTC instant, or an id that is not text a driver can bind (no NUL, no lone
    surrogate): each would fail in the driver, a 500 rather than the 400 (E40-T04, #3917)."""
    try:
        ts, rid = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        when = datetime.fromisoformat(ts)
        when.astimezone(UTC)  # an offset the instant cannot carry to UTC (year 1, +14:00)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("invalid cursor") from exc
    if when.tzinfo is None or not isinstance(rid, str) or "\x00" in rid:
        raise ValueError("invalid cursor")
    try:
        rid.encode("utf-8")  # a lone surrogate has no UTF-8 form
    except UnicodeEncodeError:
        raise ValueError("invalid cursor") from None
    return when, rid


def array_literal(values: tuple[str, ...]) -> str:
    """Postgres array literal for `alert_channel[]`; every value must be a known enum word."""
    bad = [v for v in values if v not in ALERT_CHANNELS]
    if bad:
        raise ValueError(f"invalid alert channel: {bad[0]!r}")
    return "{" + ",".join(values) + "}"


#: The one constraint that means "this name is taken" (`0014_alerts.py`); any other refusal is not.
_NAME_KEY = "ux_alerts_name"


def _refusal(name: str, state: str | None, constraint: str | None) -> Exception:
    """The error a refused alert write leaves as, from the database's facts alone (#2748):
    the name key's unique violation is `AlertNameTakenError`, anything else the typed
    `query_failure` (a CHECK or NOT NULL refusal, which the route answers 422)."""
    if state == "23505" and constraint == _NAME_KEY:
        return AlertNameTakenError(name)
    return query_failure(state, constraint)


def _alert(m: Any) -> AlertRow:
    d = dict(m)
    d["channels"] = tuple(d["channels"])
    return AlertRow(**d)


#: `channels` binds through text in `_INSERT` and `_UPDATE`: asyncpg types a direct
#: `alert_channel[]` cast's parameter as an array and refuses `array_literal`'s str (#4143).
_INSERT = sa.text(
    "INSERT INTO alerts (id, owner_user_id, name, symbol, scope_account_id, condition_ir, "
    "condition_hash, enabled, trigger_mode, cooldown_seconds, expires_at, severity, channels, "
    "webhook_url_enc, webhook_secret_enc, message_template) VALUES (CAST(:id AS uuid), "
    "CAST(:owner AS uuid), :name, :symbol, CAST(:account AS uuid), CAST(:ir AS jsonb), :hash, "
    ":enabled, CAST(:mode AS alert_trigger_mode), :cooldown, :expires_at, "
    "CAST(:severity AS severity), CAST(CAST(:channels AS text) AS alert_channel[]), "
    ":url_enc, :secret_enc, :template) RETURNING "
    "id::text AS id, owner_user_id::text AS owner_user_id, name, symbol, "
    "scope_account_id::text AS scope_account_id, condition_ir, "
    "condition_hash::text AS condition_hash, enabled, trigger_mode::text AS trigger_mode, "
    "cooldown_seconds, snoozed_until, expires_at, severity::text AS severity, "
    "channels::text[] AS channels, (webhook_url_enc IS NOT NULL) AS has_webhook, "
    "message_template, last_fired_at, fire_count, created_at, updated_at, disarm_reason"
)
_GET = sa.text(
    "SELECT "
    "id::text AS id, owner_user_id::text AS owner_user_id, name, symbol, "
    "scope_account_id::text AS scope_account_id, condition_ir, "
    "condition_hash::text AS condition_hash, enabled, trigger_mode::text AS trigger_mode, "
    "cooldown_seconds, snoozed_until, expires_at, severity::text AS severity, "
    "channels::text[] AS channels, (webhook_url_enc IS NOT NULL) AS has_webhook, "
    "message_template, last_fired_at, fire_count, created_at, updated_at, disarm_reason"
    " FROM alerts WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
)
_LIST = sa.text(
    "SELECT "
    "id::text AS id, owner_user_id::text AS owner_user_id, name, symbol, "
    "scope_account_id::text AS scope_account_id, condition_ir, "
    "condition_hash::text AS condition_hash, enabled, trigger_mode::text AS trigger_mode, "
    "cooldown_seconds, snoozed_until, expires_at, severity::text AS severity, "
    "channels::text[] AS channels, (webhook_url_enc IS NOT NULL) AS has_webhook, "
    "message_template, last_fired_at, fire_count, created_at, updated_at, disarm_reason"
    " FROM alerts WHERE owner_user_id = CAST(:owner AS uuid) "
    "AND deleted_at IS NULL AND (CAST(:enabled AS boolean) IS NULL OR enabled = :enabled) "
    "AND (CAST(:symbol AS text) IS NULL OR symbol = :symbol) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR "
    "(created_at, id::text) < (CAST(:after_ts AS timestamptz), :after_id)) "
    "ORDER BY created_at DESC, id::text DESC LIMIT :limit"
)
_UPDATE = sa.text(
    "UPDATE alerts SET name = :name, symbol = :symbol, scope_account_id = CAST(:account AS uuid), "
    "enabled = :enabled, disarm_reason = CASE WHEN :enabled THEN NULL ELSE disarm_reason END, "
    "condition_ir = CAST(:ir AS jsonb), condition_hash = :hash, "
    "trigger_mode = CAST(:mode AS alert_trigger_mode), cooldown_seconds = :cooldown, "
    "expires_at = :expires_at, severity = CAST(:severity AS severity), "
    "channels = CAST(CAST(:channels AS text) AS alert_channel[]), message_template = :template, "
    "updated_at = clock_timestamp() WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL "
    "AND updated_at = :if_match RETURNING "
    "id::text AS id, owner_user_id::text AS owner_user_id, name, symbol, "
    "scope_account_id::text AS scope_account_id, condition_ir, "
    "condition_hash::text AS condition_hash, enabled, trigger_mode::text AS trigger_mode, "
    "cooldown_seconds, snoozed_until, expires_at, severity::text AS severity, "
    "channels::text[] AS channels, (webhook_url_enc IS NOT NULL) AS has_webhook, "
    "message_template, last_fired_at, fire_count, created_at, updated_at, disarm_reason"
)
_SOFT_DELETE = sa.text(
    "UPDATE alerts SET deleted_at = now(), enabled = false, updated_at = clock_timestamp() "
    "WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
)
_SET_ENABLED = sa.text(
    "UPDATE alerts SET enabled = :enabled, "
    "disarm_reason = CASE WHEN :enabled THEN NULL ELSE disarm_reason END, "
    "updated_at = clock_timestamp() WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL RETURNING "
    "id::text AS id, owner_user_id::text AS owner_user_id, name, symbol, "
    "scope_account_id::text AS scope_account_id, condition_ir, "
    "condition_hash::text AS condition_hash, enabled, trigger_mode::text AS trigger_mode, "
    "cooldown_seconds, snoozed_until, expires_at, severity::text AS severity, "
    "channels::text[] AS channels, (webhook_url_enc IS NOT NULL) AS has_webhook, "
    "message_template, last_fired_at, fire_count, created_at, updated_at, disarm_reason"
)
_SET_SNOOZE = sa.text(
    "UPDATE alerts SET snoozed_until = :until, updated_at = clock_timestamp() "
    "WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL RETURNING "
    "id::text AS id, owner_user_id::text AS owner_user_id, name, symbol, "
    "scope_account_id::text AS scope_account_id, condition_ir, "
    "condition_hash::text AS condition_hash, enabled, trigger_mode::text AS trigger_mode, "
    "cooldown_seconds, snoozed_until, expires_at, severity::text AS severity, "
    "channels::text[] AS channels, (webhook_url_enc IS NOT NULL) AS has_webhook, "
    "message_template, last_fired_at, fire_count, created_at, updated_at, disarm_reason"
)
_BUMP = sa.text(
    "UPDATE alerts SET fire_count = fire_count + 1, last_fired_at = :fired_at "
    "WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
)
_ARMED = sa.text(
    "SELECT "
    "id::text AS id, owner_user_id::text AS owner_user_id, name, symbol, "
    "scope_account_id::text AS scope_account_id, condition_ir, "
    "condition_hash::text AS condition_hash, enabled, trigger_mode::text AS trigger_mode, "
    "cooldown_seconds, snoozed_until, expires_at, severity::text AS severity, "
    "channels::text[] AS channels, (webhook_url_enc IS NOT NULL) AS has_webhook, "
    "message_template, last_fired_at, fire_count, created_at, updated_at, disarm_reason"
    " FROM alerts WHERE symbol = :symbol AND enabled AND deleted_at IS NULL"
)
_COUNT_ENABLED = sa.text(
    "SELECT enabled, count(*) AS n FROM alerts WHERE deleted_at IS NULL GROUP BY enabled"
)
_COUNT_PENDING = sa.text("SELECT count(*) FROM alert_deliveries WHERE status = 'queued'")
# #1864: the owner's armed-alert cap lock, then its count. Race-free under READ COMMITTED, the
# server default this engine keeps: each statement after the lock sees the previous holder's
# commit (the drawings `_QUOTA_LOCK` reasoning, #2727). A disarm never takes it.
_ARMED_LOCK = sa.text(
    "SELECT pg_advisory_xact_lock(hashtextextended('cv.alerts_armed:' || CAST(:owner AS text), 0))"
)
# The owner's armed alerts other than `:id` (NULL on a create), and whether `:id` is armed.
_ARMED_COUNT = sa.text(
    "SELECT count(*) FILTER (WHERE id IS DISTINCT FROM CAST(:id AS uuid)) AS others, "
    "coalesce(bool_or(id = CAST(:id AS uuid)), false) AS target_armed FROM alerts "
    "WHERE owner_user_id = CAST(:owner AS uuid) AND enabled AND deleted_at IS NULL"
)
# The live target of a replace or `set_enabled`: its owner (for the lock) and concurrency token.
_TARGET = sa.text(
    "SELECT owner_user_id::text AS owner, updated_at FROM alerts "
    "WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
)


class SqlAlchemyAlertRepository:
    def __init__(
        self, relational: SqlAlchemyRelationalRepository, *, max_armed: int = MAX_ARMED_ALERTS
    ) -> None:
        self._relational = relational
        self._max_armed = max_armed

    async def _hold_armed_cap(
        self, uow: SqlAlchemyUnitOfWork, owner: str, alert_id: str | None
    ) -> None:
        """Arming `alert_id` (None: a new alert) for `owner`: take the cap lock, then refuse
        with `AlertArmedLimitError` past the cap. Call inside the write's transaction."""
        await uow.session.execute(_ARMED_LOCK, {"owner": owner})
        got = (
            (await uow.session.execute(_ARMED_COUNT, {"owner": owner, "id": alert_id}))
            .mappings()
            .one()
        )
        refused = armed_breach(
            int(got["others"]), arming=not got["target_armed"], limit=self._max_armed
        )
        if refused is not None:
            raise refused

    async def _hold_arming_target(
        self, uow: SqlAlchemyUnitOfWork, alert_id: str, if_match: datetime | None = None
    ) -> None:
        """A replace or `set_enabled` that sets `enabled`: hold the cap for its live target. A
        missing target, or a stale `if_match`, is left to the write (404 / 412), never refused."""
        target = (await uow.session.execute(_TARGET, {"id": alert_id})).mappings().first()
        if target is None or (if_match is not None and target["updated_at"] != if_match):
            return
        await self._hold_armed_cap(uow, str(target["owner"]), alert_id)

    async def create(
        self,
        *,
        owner_user_id: str,
        alert_id: str | None = None,
        name: str,
        condition_ir: dict[str, Any],
        condition_hash: str,
        symbol: str | None = None,
        scope_account_id: str | None = None,
        enabled: bool = True,
        trigger_mode: str = "once",
        cooldown_seconds: int = 60,
        expires_at: datetime | None = None,
        severity: str = "info",
        channels: tuple[str, ...] = ("in_app",),
        webhook_url_enc: bytes | None = None,
        webhook_secret_enc: bytes | None = None,
        message_template: str = "",
    ) -> AlertRow:
        params: dict[str, Any] = {
            "id": alert_id or str(uuid.uuid4()),
            "owner": owner_user_id,
            "name": name,
            "symbol": symbol,
            "account": scope_account_id,
            "ir": json.dumps(condition_ir, sort_keys=True),
            "hash": condition_hash,
            "enabled": enabled,
            "mode": trigger_mode,
            "cooldown": cooldown_seconds,
            "expires_at": expires_at,
            "severity": severity,
            "channels": array_literal(channels),
            "url_enc": webhook_url_enc,
            "secret_enc": webhook_secret_enc,
            "template": message_template,
        }
        try:
            async with self._relational.unit_of_work() as uow:
                if enabled:
                    await self._hold_armed_cap(uow, owner_user_id, None)
                row = (await uow.session.execute(_INSERT, params)).mappings().one()
                await uow.commit()
        except IntegrityError as exc:
            raise _refusal(name, sqlstate_of(exc), constraint_of(exc)) from None
        return _alert(row)

    async def get(self, alert_id: str) -> AlertRow | None:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_GET, {"id": alert_id})).mappings().first()
        return None if row is None else _alert(row)

    async def list_page(
        self,
        owner_user_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        enabled: bool | None = None,
        symbol: str | None = None,
    ) -> Page[AlertRow]:
        after_ts, after_id = decode_cursor(cursor) if cursor else (None, None)
        params: dict[str, Any] = {
            "owner": owner_user_id,
            "enabled": enabled,
            "symbol": symbol,
            "after_ts": after_ts,
            "after_id": after_id,
            "limit": limit + 1,
        }
        async with self._relational.unit_of_work() as uow:
            rows = [_alert(r) for r in (await uow.session.execute(_LIST, params)).mappings()]
        more = len(rows) > limit
        rows = rows[:limit]
        nxt = encode_cursor(rows[-1].created_at, rows[-1].id) if more and rows else None
        return Page(rows, nxt)

    async def update(
        self,
        alert_id: str,
        *,
        if_match: datetime,
        name: str,
        condition_ir: dict[str, Any],
        condition_hash: str,
        trigger_mode: str,
        cooldown_seconds: int,
        expires_at: datetime | None,
        severity: str,
        channels: tuple[str, ...],
        message_template: str,
        symbol: str | None = None,
        scope_account_id: str | None = None,
        enabled: bool = True,
    ) -> AlertRow:
        """Optimistic concurrency: `if_match` is the `updated_at` the caller read."""
        params: dict[str, Any] = {
            "id": alert_id,
            "symbol": symbol,
            "account": scope_account_id,
            "enabled": enabled,
            "if_match": if_match,
            "name": name,
            "ir": json.dumps(condition_ir, sort_keys=True),
            "hash": condition_hash,
            "mode": trigger_mode,
            "cooldown": cooldown_seconds,
            "expires_at": expires_at,
            "severity": severity,
            "channels": array_literal(channels),
            "template": message_template,
        }
        try:
            async with self._relational.unit_of_work() as uow:
                if enabled:
                    await self._hold_arming_target(uow, alert_id, if_match)
                row = (await uow.session.execute(_UPDATE, params)).mappings().first()
                await uow.commit()
        except IntegrityError as exc:
            raise _refusal(name, sqlstate_of(exc), constraint_of(exc)) from None
        if row is None:
            raise AlertConflictError(alert_id)
        return _alert(row)

    async def soft_delete(self, alert_id: str) -> bool:
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_SOFT_DELETE, {"id": alert_id})
            await uow.commit()
        return bool(getattr(res, "rowcount", 0))

    async def set_enabled(self, alert_id: str, enabled: bool) -> AlertRow | None:
        if not enabled:  # a disarm is never held to the cap
            return await self._one(_SET_ENABLED, {"id": alert_id, "enabled": False})
        async with self._relational.unit_of_work() as uow:
            await self._hold_arming_target(uow, alert_id)
            row = (
                (await uow.session.execute(_SET_ENABLED, {"id": alert_id, "enabled": True}))
                .mappings()
                .first()
            )
            await uow.commit()
        return None if row is None else _alert(row)

    async def set_snooze(self, alert_id: str, until: datetime | None) -> AlertRow | None:
        return await self._one(_SET_SNOOZE, {"id": alert_id, "until": until})

    async def bump_fire_counters(self, alert_id: str, fired_at: datetime) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_BUMP, {"id": alert_id, "fired_at": fired_at})
            await uow.commit()

    async def load_armed(self, symbol: str) -> list[AlertRow]:
        """Evaluator warm-up query; served by partial index `ix_alerts_live`."""
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_ARMED, {"symbol": symbol})).mappings()
            return [_alert(r) for r in rows]

    async def gauges(self) -> dict[str, int]:
        """Source for `cv_alerts_total{enabled}` and `cv_alert_deliveries_pending`."""
        async with self._relational.unit_of_work() as uow:
            by_enabled = (await uow.session.execute(_COUNT_ENABLED)).mappings().all()
            pending = int((await uow.session.execute(_COUNT_PENDING)).scalar_one())
        counts = {bool(r["enabled"]): int(r["n"]) for r in by_enabled}
        return {
            "cv_alerts_total{enabled=true}": counts.get(True, 0),
            "cv_alerts_total{enabled=false}": counts.get(False, 0),
            "cv_alert_deliveries_pending": pending,
        }

    async def _one(self, stmt: sa.TextClause, params: dict[str, Any]) -> AlertRow | None:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(stmt, params)).mappings().first()
            await uow.commit()
        return None if row is None else _alert(row)


__all__ = [
    "ALERT_CHANNELS", "ALERT_COLUMNS", "AlertConflictError", "AlertNameTakenError", "AlertRow",
    "Page", "SqlAlchemyAlertRepository", "array_literal", "decode_cursor", "encode_cursor",
]  # fmt: skip
