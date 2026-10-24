"""E42-Q01 (#962): the admin fixtures' handles are synthetic, deterministic and complete.

The security note of #962: no fixture holds a credential, an exchange key or personal data, which
this checks with the log redactor's own patterns. The seed and its check are
`tests/unit/test_admin_fixture_seed.py`; the seed's database half is
`tests/integration/admin/test_admin_fixture_seed_pg.py`.
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from pathlib import Path

import argon2
import pytest
from sqlalchemy import CheckConstraint

from candleviewer.admin.flags.catalogue import FLAGS as CATALOGUE
from candleviewer.admin.flags.registry import FlagKind
from candleviewer.auth.hashing import Hasher
from candleviewer.db import models as m
from candleviewer.observability.redaction import redact_text
from candleviewer.storage.repositories.backups import BACKUP_ERROR_CODES
from candleviewer.storage.repositories.backups_sqlalchemy import _path as backup_path_rule
from tests.fixtures.admin.handles import (
    ACCOUNTS,
    BACKUP_VERIFY_FAILED,
    BACKUPS,
    FLAGS,
    GRANTS,
    KEY_RESTRICTION,
    PLACEHOLDER_HASH,
    USERS,
    FixtureBackup,
    account,
    fixture_id,
)
from tests.fixtures.admin.seed import is_test_database

_README = Path(__file__).resolve().parents[1] / "fixtures" / "admin" / "README.md"
#: Each defeats one loosening of the rule: `endswith("test")`, `"_test" in`, `.lower()`.
_REFUSE = "candleviewer testdb test_candleviewer prod latest candleviewer_test_backup Test".split()


def _values() -> list[str]:
    users = [s for u in USERS for s in (u.handle, u.username, u.email)]
    accounts = [s for a in ACCOUNTS for s in (a.handle, a.label, a.exchange_uid)]
    backups = [
        s for b in BACKUPS for s in (b.handle, b.target_path, b.checksum_sha256, b.error) if s
    ]
    return [*users, *accounts, *backups, *FLAGS, PLACEHOLDER_HASH]


def _uid_format() -> re.Pattern[str]:
    """The pattern of the `ea_uid_fmt` CHECK, read from the model: `exchange_uid ~ '<pattern>'`."""
    checks = [c for c in m.exchange_accounts.constraints if isinstance(c, CheckConstraint)]
    check = next(c for c in checks if str(c.name).endswith("ea_uid_fmt"))
    found = re.fullmatch(r"exchange_uid ~ '(.+)'", str(check.sqltext))
    assert found is not None, check.sqltext
    return re.compile(found.group(1))


@pytest.mark.parametrize("value", _values())
def test_no_fixture_value_is_secret_shaped(value: str) -> None:
    assert redact_text(value) == value


#: A window of whole lines, and how far each starts after the one before, in characters. Both are
#: far under the redactor's cut: it changes any text over 4,119 characters, secret-shaped or not, so
#: a whole file cannot be scanned at once. Two lines less than `_WINDOW - _STEP` characters apart
#: share a window, blank lines between them kept: the redactor reads a label's value past them.
_WINDOW, _STEP = 2000, 500


def _changes(text: str) -> bool:
    return redact_text(text) != text


def _secret_shaped_lines(text: str) -> list[int]:
    """For each window of `text` that the redactor changes, the number of the line that completes
    the window's first secret-shaped text, as the redactor reads it: a label's value, on the label's
    line or past blank lines, or a key or token shape. Two secrets in one window give one number.
    Numbers only, so that a failure never prints the text. A single line over the cut is reported
    too, as it fails closed."""
    lines = text.splitlines()
    found: set[int] = set()
    first = 0
    while first < len(lines):
        last, size = first + 1, len(lines[first]) + 1
        while last < len(lines) and size + len(lines[last]) + 1 <= _WINDOW:
            size += len(lines[last]) + 1
            last += 1
        if _changes("\n".join(lines[first:last])):
            ends = (e for e in range(first + 1, last + 1) if _changes("\n".join(lines[first:e])))
            found.add(next(ends))  # the shortest start of the window that the redactor changes
        start, skipped = first, 0
        while first < last and (skipped < _STEP or first == start):
            skipped += len(lines[first]) + 1  # on by `_STEP` characters, and one line at least
            first += 1
    return sorted(found)


def test_no_readme_window_is_secret_shaped() -> None:
    flagged = _secret_shaped_lines(_README.read_text(encoding="utf-8"))
    assert flagged == []  # line numbers, never the text


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("A fine paragraph.\n\nSee below.\npassword:\nnot-a-value-1\n", [5]),
        ("A fine paragraph.\n\nSee below.\npassword:\n\nnot-a-value-1\n", [6]),
        ("A fine paragraph.\n\nSee below.\npassword:\n\n\n\nnot-a-value-1\n", [8]),
        ("\n".join(["Plain prose."] * 400 + ["password: not-a-value-1"]), [401]),
    ],
    ids=["next-line", "after-a-blank-line", "after-three-blank-lines", "late-in-a-long-file"],
)
def test_the_readme_scan_catches_a_label_with_its_value_past_the_line_end(
    text: str, flagged: list[int]
) -> None:
    assert _secret_shaped_lines(text) == flagged


_PROSE = "Plain prose."  # 13 characters a line, with its line end
_LONG_LABEL = " ".join([_PROSE] * 45) + " password:"  # one line of 594 characters


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        # 1,989 characters of lines first: the first window ends after the label, before its value
        ("\n".join([_PROSE] * 153 + ["password:", "not-a-value-1"]), [155]),
        # 1,398 characters first, then a long label line: the next window must start in the prose
        ("\n".join([_PROSE] * 107 + ["Prose.", _LONG_LABEL, "not-a-value-1"]), [110]),
    ],
    ids=["after-a-full-window", "a-long-label-line-after-most-of-a-window"],
)
def test_the_readme_scan_catches_a_label_and_its_value_across_a_window_end(
    text: str, flagged: list[int]
) -> None:
    assert _secret_shaped_lines(text) == flagged  # only an overlapping next window holds both


def test_the_readme_scan_reports_the_line_that_ends_the_secret_not_the_window() -> None:
    text = "password:\nnot-a-value-1\n" + "\n".join([_PROSE] * 50)
    assert _secret_shaped_lines(text) == [2]


def test_the_readme_scan_reports_a_single_line_over_the_cut() -> None:
    line = " ".join([_PROSE] * 400)
    assert len(line) > 4119
    assert _secret_shaped_lines(line) == [1]


def test_the_readme_scan_does_not_flag_a_long_paragraph_for_its_length() -> None:
    paragraph = "\n".join(f"A plain line of prose, number {i}." for i in range(300))  # over the cut
    assert len(paragraph) > 4119
    assert _secret_shaped_lines(paragraph) == []


async def test_the_placeholder_hash_verifies_no_password() -> None:
    with pytest.raises(argon2.exceptions.VerificationError, match="Decoding failed"):
        argon2.low_level.verify_secret(PLACEHOLDER_HASH.encode(), b"fixture", argon2.Type.ID)
    assert await Hasher(pepper="fixture-pepper").verify(PLACEHOLDER_HASH, "fixture") is False


def test_a_fixture_id_is_the_same_on_every_run() -> None:
    assert fixture_id("OWNER") == uuid.UUID("deaeba83-565f-5c87-8672-94c57e7a15be")


@pytest.mark.parametrize("handle", [a.handle for a in ACCOUNTS])
def test_an_account_uid_matches_the_ea_uid_fmt_check(handle: str) -> None:
    assert _uid_format().fullmatch(account(handle).exchange_uid)


def test_the_ea_uid_fmt_pattern_refuses_a_label() -> None:
    assert _uid_format().fullmatch("fixture-main") is None


def test_the_users_cover_every_status() -> None:
    assert {u.status for u in USERS} == {"invited", "active", "disabled", "locked"}


def test_the_users_cover_every_role() -> None:
    assert {u.role for u in USERS} == {"owner", "manager", "viewer"}


def test_the_handles_are_unique() -> None:
    handles = [u.handle for u in USERS] + [a.handle for a in ACCOUNTS] + [b.handle for b in BACKUPS]
    assert len(handles) == len(set(handles))


def test_the_trade_grants_are_none_one_and_many() -> None:
    assert sorted(len(granted) for granted in GRANTS.values()) == [0, 1, 3]


def test_only_sub_k_is_inside_the_key_restriction() -> None:
    assert {a.handle for a in ACCOUNTS if a.age < KEY_RESTRICTION} == {"SUB-K"}


def test_the_key_restriction_is_48_hours() -> None:
    assert KEY_RESTRICTION == timedelta(hours=48)


def test_the_flags_are_catalogued_booleans() -> None:
    kinds = {spec.key: spec.kind for spec in CATALOGUE}
    assert {key: kinds.get(key) for key in FLAGS} == dict.fromkeys(FLAGS, FlagKind.BOOLEAN)


def test_the_live_gate_is_seeded_blocked() -> None:
    assert FLAGS["trading.live_enabled"] is False


@pytest.mark.parametrize("name", ["test", "candleviewer_test"])
def test_a_database_named_for_tests_is_seeded(name: str) -> None:
    assert is_test_database(name)


@pytest.mark.parametrize("name", _REFUSE)
def test_any_other_database_is_refused(name: str) -> None:
    assert not is_test_database(name)


def test_the_backups_newest_first_are_the_failed_one_and_the_verified_one() -> None:
    assert [b.status for b in sorted(BACKUPS, key=lambda b: b.age)] == ["failed", "verified"]


def test_the_failed_backup_failed_on_its_digest() -> None:
    assert BACKUP_VERIFY_FAILED.error == "checksum_mismatch"


def test_the_failed_backups_code_is_one_the_store_records() -> None:
    assert BACKUP_VERIFY_FAILED.error in BACKUP_ERROR_CODES


@pytest.mark.parametrize("backup", BACKUPS, ids=[b.handle for b in BACKUPS])
def test_a_backups_path_passes_the_stores_rule_for_a_target_path(backup: FixtureBackup) -> None:
    assert backup_path_rule(backup.target_path) == backup.target_path


@pytest.mark.parametrize("backup", BACKUPS, ids=[b.handle for b in BACKUPS])
def test_a_backups_digest_is_sha256_hex(backup: FixtureBackup) -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", backup.checksum_sha256)
