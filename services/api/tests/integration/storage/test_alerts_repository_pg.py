"""Integration (#2748, slice 3a) on real Postgres 16: an alert write the database refuses leaves
`SqlAlchemyAlertRepository` as a typed error that carries no row value (C-12.6). Each planted value
is first shown to be in the server's own text (`server_text`), then absent from what leaves. Needs
docker (testcontainers); exercised by CI `integration`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from candleviewer.storage.errors import StorageConstraintViolated
from candleviewer.storage.repositories.alerts import AlertNameTakenError, AlertRow
from candleviewer.storage.repositories.alerts_sqlalchemy import SqlAlchemyAlertRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.integration import _refused
from tests.integration._refused import (
    assert_no_markers,
    assert_no_row_values,
    seed_user,
    server_text,
)

pytestmark = pytest.mark.integration
pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head
# Stand in for the SECRET `webhook_*_enc` bytea; under 31 bytes, so `\x<hex>` fits DETAIL's cut.
_URL = b"SECRET-URL-ENC"
_SECRET = b"SECRET-HMAC-ENC"
_PLANTED = {"webhook_url_enc": _URL, "webhook_secret_enc": _SECRET}
_ALERT: dict[str, Any] = {"condition_ir": {"conditions": {}}, "condition_hash": "a" * 64}
_TYPED = (None, True)  # `(__cause__, __suppress_context__)` of an error raised `from None`
_UPDATABLE = (
    "name condition_ir condition_hash trigger_mode cooldown_seconds expires_at severity channels "
    "message_template symbol scope_account_id enabled"
).split()  # what `update` takes besides the id and `if_match`


@pytest_asyncio.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "alerts-refused-it")
    try:
        yield rel
    finally:
        await rel.dispose()


@pytest.fixture
def repo(rel: SqlAlchemyRelationalRepository) -> SqlAlchemyAlertRepository:
    return SqlAlchemyAlertRepository(rel)


@pytest.fixture
def owner(pg_dsn: str) -> str:
    return seed_user(pg_dsn)  # a fresh owner per test: the name key is per owner


async def _create(repo: SqlAlchemyAlertRepository, owner: str, name: str, **over: Any) -> AlertRow:
    return await repo.create(owner_user_id=owner, name=name, **_ALERT, **over)


async def _update(repo: SqlAlchemyAlertRepository, row: AlertRow, **over: Any) -> AlertRow:
    fields = {k: getattr(row, k) for k in _UPDATABLE} | over  # the row as it is, `over` changed
    return await repo.update(row.id, if_match=row.updated_at, **fields)


async def test_a_name_in_another_case_is_taken_on_create(
    rel: SqlAlchemyRelationalRepository, repo: SqlAlchemyAlertRepository, owner: str
) -> None:
    await _create(repo, owner, "Breakout")
    with server_text(rel) as seen, pytest.raises(AlertNameTakenError) as err:
        await _create(repo, owner, "BREAKOUT")
    assert (err.value.__cause__, err.value.__suppress_context__) == _TYPED
    # The unique violation's DETAIL is `Key (owner_user_id, lower(name))=(<owner>, ...)`.
    assert_no_row_values(err.value, seen, owner)


async def test_a_name_in_another_case_is_taken_on_update(
    rel: SqlAlchemyRelationalRepository, repo: SqlAlchemyAlertRepository, owner: str
) -> None:
    await _create(repo, owner, "Breakout")
    other = await _create(repo, owner, "Reversal")
    with server_text(rel) as seen, pytest.raises(AlertNameTakenError) as err:
        await _update(repo, other, name="BREAKOUT")
    assert (err.value.__cause__, err.value.__suppress_context__) == _TYPED
    assert_no_row_values(err.value, seen, owner)


async def test_a_soft_deleted_name_is_free_to_reuse(
    repo: SqlAlchemyAlertRepository, owner: str
) -> None:
    gone = await _create(repo, owner, "Breakout")
    assert await repo.soft_delete(gone.id)
    again = await _create(repo, owner, "BREAKOUT")  # `ux_alerts_name` is partial on live rows
    assert (again.name, again.id != gone.id) == ("BREAKOUT", True)


async def test_a_22_character_symbol_is_refused_by_the_symbol_domain(
    rel: SqlAlchemyRelationalRepository, repo: SqlAlchemyAlertRepository, owner: str
) -> None:
    # A domain CHECK has no DETAIL, so there is no value to plant: the facts, and no marker.
    with server_text(rel) as seen, pytest.raises(StorageConstraintViolated) as err:
        await _create(repo, owner, "Breakout", symbol="A" * 22)
    assert (err.value.sqlstate, err.value.constraint) == ("23514", "symbol_code_check")
    assert (err.value.__cause__, err.value.__suppress_context__) == _TYPED
    assert_no_markers(err.value, seen)  # the statement's text too, which has no value to plant


async def test_a_cooldown_over_a_planted_ciphertext_is_refused_on_create(
    rel: SqlAlchemyRelationalRepository, repo: SqlAlchemyAlertRepository, owner: str
) -> None:
    with server_text(rel) as seen, pytest.raises(StorageConstraintViolated) as err:
        await _create(repo, owner, "Breakout", cooldown_seconds=86_401, **_PLANTED)
    assert (err.value.sqlstate, err.value.constraint) == ("23514", "al_cooldown")
    assert (err.value.__cause__, err.value.__suppress_context__) == _TYPED
    assert_no_row_values(err.value, seen, _URL, _SECRET)  # `Failing row contains (..., \x<hex>)`


async def test_a_cooldown_over_a_planted_ciphertext_is_refused_on_update(
    rel: SqlAlchemyRelationalRepository, repo: SqlAlchemyAlertRepository, owner: str
) -> None:
    row = await _create(repo, owner, "Breakout", **_PLANTED)
    with server_text(rel) as seen, pytest.raises(StorageConstraintViolated) as err:
        await _update(repo, row, cooldown_seconds=86_401)  # the new row still holds the ciphertexts
    assert (err.value.sqlstate, err.value.constraint) == ("23514", "al_cooldown")
    assert (err.value.__cause__, err.value.__suppress_context__) == _TYPED
    assert_no_row_values(err.value, seen, _URL, _SECRET)
