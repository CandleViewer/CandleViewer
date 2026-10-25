"""The break-glass CLI's Postgres side without a database (E09-S11 #2119 slice 5): every
session of its pool is named for the run (R2c), and its KCV store cannot enrol a KEK (O1).
The probe itself runs on Postgres in `tests/integration/auth/test_breakglass_cli_pg.py`."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.storage.errors import KcvEnrolmentNotAudited
from candleviewer.storage.repositories import bootstrap_owner_sqlalchemy as mint
from candleviewer.storage.repositories.bootstrap_owner_sqlalchemy import (
    SqlAlchemyBootstrapOwnerRepository,
)
from candleviewer.storage.repositories.break_glass_cli_sqlalchemy import (
    SqlAlchemyBootstrapOwnerDatabase,
    SqlAlchemyBreakGlassDatabase,
)
from candleviewer.storage.repositories.break_glass_sqlalchemy import (
    SqlAlchemyBreakGlassRepository,
)
from candleviewer.storage.repositories.invites_sqlalchemy import BOOTSTRAP_MARKER

_DSN = "postgresql+asyncpg://cv@127.0.0.1:1/candleviewer"  # never connected to


async def test_every_session_is_named_for_the_run() -> None:
    first, second = SqlAlchemyBreakGlassDatabase(_DSN), SqlAlchemyBreakGlassDatabase(_DSN)
    try:
        assert first.application_name.startswith("candleviewer:breakglass:")
        assert first.application_name != second.application_name
        cparams: dict[str, Any] = {"server_settings": {"timezone": "UTC"}}
        first._name_session(None, None, [], cparams)
        assert cparams["server_settings"] == {
            "timezone": "UTC",
            "application_name": first.application_name,
        }
    finally:
        await first.dispose()
        await second.dispose()


async def test_kcv_store_cannot_enrol_a_kek() -> None:
    database = SqlAlchemyBreakGlassDatabase(_DSN)
    try:
        with pytest.raises(KcvEnrolmentNotAudited):
            await database.kcv.record_kcv("demo", 1, bytes(32), audit=("unused", {}))
    finally:
        await database.dispose()


async def test_each_cli_composes_only_its_own_writer() -> None:
    """DC-4479-17 (C1): a break-glass run holds no Owner-invite mint, a bootstrap run no reset
    store; both share the journal's stores and the probe, each under its own session name."""
    glass, boot = SqlAlchemyBreakGlassDatabase(_DSN), SqlAlchemyBootstrapOwnerDatabase(_DSN)
    try:
        held = [{type(value) for value in vars(db).values()} for db in (glass, boot)]
        assert SqlAlchemyBreakGlassRepository in held[0] - held[1]  # the reset store
        assert SqlAlchemyBootstrapOwnerRepository in held[1] - held[0]  # the mint
        assert hasattr(glass, "owners") and not hasattr(glass, "bootstrap_owners")
        assert hasattr(boot, "bootstrap_owners") and not hasattr(boot, "owners")
        for name in ("audit_log", "kcv", "others_connected", "reachable", "dispose"):
            assert hasattr(glass, name) and hasattr(boot, name)
        assert boot.application_name.startswith("candleviewer:bootstrap:")
        cparams: dict[str, Any] = {}
        boot._name_session(None, None, [], cparams)
        assert cparams == {"server_settings": {"application_name": boot.application_name}}
    finally:
        await glass.dispose()
        await boot.dispose()


def test_the_mint_statements_are_whole_literals_kept_in_step() -> None:
    """B608: no statement of the mint is spliced (#4479 C1), so these keep them in step: the
    supersede carries `BOOTSTRAP_MARKER` verbatim, and the locked read is the state read's."""
    assert BOOTSTRAP_MARKER in str(mint._SUPERSEDE)
    assert str(mint._LOCK_CANDIDATE) == f"{mint._READ_CANDIDATE} FOR UPDATE OF u"
