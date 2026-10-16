"""Alembic environment for CandleViewer's Postgres schema (M10 `storage`).

`target_metadata` is `candleviewer.db.models.metadata` (E07-T02) so
`alembic check` (autogenerate-drift CI gate) has a source of truth to diff
migration history against. The `sqlalchemy.url` is resolved from
`Settings.pg_dsn` at runtime — never hard-coded here (C-12.2, no secrets in
code); `CV_PG_DSN` overrides it directly for tooling (e.g. the integration
test's testcontainers DSN) without going through `.env`.

Alembic runs synchronously: whichever source the URL comes from, it is
normalised to the sync psycopg 3 driver (`postgresql+psycopg://`) — an async
driver here raises `MissingGreenlet` (see `candleviewer.migrations.boot`).
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from candleviewer.db.models import metadata as target_metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _get_url() -> str:
    from candleviewer.migrations.dsn import to_sync_dsn

    # `CV_PG_DSN` env override takes priority so tooling (the identity-migration
    # integration test, `alembic upgrade --sql` in CI) can point at a
    # testcontainers/scratch DSN without touching `.env` or `Settings` defaults.
    override = os.environ.get("CV_PG_DSN")
    if override:
        return to_sync_dsn(override)

    from candleviewer.settings import get_settings

    return to_sync_dsn(get_settings().pg_dsn.get_secret_value())


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection ("offline" mode)."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection ("online" mode)."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # A failed statement's exception text otherwise renders its bound values (C-12.6).
        hide_parameters=True,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
