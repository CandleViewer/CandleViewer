"""E42-Q01 (#962): the admin fixtures' handles are synthetic, deterministic and complete.

The security note of #962: no fixture holds a credential, an exchange key or personal data, which
this checks with the log redactor's own patterns. The seed's database half is
`tests/integration/admin/test_admin_fixture_seed_pg.py`.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from pathlib import Path

import pytest

from candleviewer.admin.flags.catalogue import FLAGS as CATALOGUE
from candleviewer.admin.flags.registry import FlagKind
from candleviewer.auth.hashing import Hasher
from candleviewer.observability.redaction import redact_text
from tests.fixtures.admin.handles import (
    ACCOUNTS,
    FLAGS,
    GRANTS,
    KEY_RESTRICTION,
    PLACEHOLDER_HASH,
    USERS,
    fixture_id,
)
from tests.fixtures.admin.seed import is_test_database

_README = Path(__file__).resolve().parents[1] / "fixtures" / "admin" / "README.md"


def _values() -> list[str]:
    users = [s for u in USERS for s in (u.handle, u.username, u.email)]
    accounts = [s for a in ACCOUNTS for s in (a.handle, a.label, a.exchange_uid)]
    return [*users, *accounts, *FLAGS, PLACEHOLDER_HASH]


@pytest.mark.parametrize("value", _values())
def test_no_fixture_value_is_secret_shaped(value: str) -> None:
    assert redact_text(value) == value


def test_the_readme_holds_nothing_secret_shaped() -> None:
    text = _README.read_text(encoding="utf-8")
    assert redact_text(text) == text


async def test_the_placeholder_hash_verifies_no_password() -> None:
    hasher = Hasher(pepper=os.urandom(16).hex())
    assert await hasher.verify(PLACEHOLDER_HASH, "fixture") is False


def test_a_fixture_id_is_the_same_on_every_run() -> None:
    assert fixture_id("OWNER") == uuid.UUID("deaeba83-565f-5c87-8672-94c57e7a15be")


def test_the_users_cover_every_status_and_role() -> None:
    assert {u.status for u in USERS} == {"invited", "active", "disabled", "locked"}
    assert {u.role for u in USERS} == {"owner", "manager", "viewer"}


def test_the_handles_are_unique() -> None:
    handles = [u.handle for u in USERS] + [a.handle for a in ACCOUNTS]
    assert len(handles) == len(set(handles))


def test_the_trade_grants_are_none_one_and_many() -> None:
    assert sorted(len(granted) for granted in GRANTS.values()) == [0, 1, 3]


def test_only_sub_k_is_inside_the_key_restriction() -> None:
    inside = {a.handle for a in ACCOUNTS if a.age < KEY_RESTRICTION}
    assert inside == {"SUB-K"} and KEY_RESTRICTION == timedelta(hours=48)


def test_the_flags_are_catalogued_booleans() -> None:
    kinds = {spec.key: spec.kind for spec in CATALOGUE}
    assert {key: kinds.get(key) for key in FLAGS} == dict.fromkeys(FLAGS, FlagKind.BOOLEAN)


def test_the_live_gate_is_seeded_blocked() -> None:
    assert FLAGS["trading.live_enabled"] is False


@pytest.mark.parametrize("name", ["test", "candleviewer_test"])
def test_a_database_named_for_tests_is_seeded(name: str) -> None:
    assert is_test_database(name)


@pytest.mark.parametrize("name", ["candleviewer", "testdb", "test_candleviewer", "prod"])
def test_any_other_database_is_refused(name: str) -> None:
    assert not is_test_database(name)
