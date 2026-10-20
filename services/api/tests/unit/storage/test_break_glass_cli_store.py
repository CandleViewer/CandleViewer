"""The break-glass CLI's Postgres side without a database (E09-S11 #2119 slice 5): every
session of its pool is named for the run (R2c), and its KCV store cannot enrol a KEK (O1).
The probe itself runs on Postgres in `tests/integration/auth/test_breakglass_cli_pg.py`."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.storage.errors import KcvEnrolmentNotAudited
from candleviewer.storage.repositories.break_glass_cli_sqlalchemy import (
    SqlAlchemyBreakGlassDatabase,
)

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
