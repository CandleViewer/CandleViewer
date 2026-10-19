"""Unit (#966 BK-11, review F1): `redact()` keeps a secret-named key's value only when it is
exactly one of that key's fixed words (`_ENUM_PASS_THROUGH`): `bearer` is `matched` or `absent`,
`downloadBackup`'s flag. Any other value under `bearer` is masked, and no other key passes. The
table itself is pinned: a word or a key added to it fails here, so it stays a reviewed edit."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest

import candleviewer.audit.redact as redact_module
from candleviewer.audit.redact import REDACTION_MARKER, redact


@pytest.mark.parametrize("word", ["matched", "absent"])
def test_a_bearer_flag_word_is_kept_at_the_top_and_nested(word: str) -> None:
    state = {
        "stage": "served",
        "bearer": word,
        "fetch": {"Bearer": word, "steps": [{"bearer": word}]},
    }
    assert redact(state) == state


@pytest.mark.parametrize(
    "value",
    ["Matched", " absent", "absent\n", "matched ", "Bearer abc", "s3cr3t-value", {"x": "matched"},
     ["matched"], None, 1],
    ids=["case", "leading", "newline", "trailing", "credential", "secret", "dict", "list", "none",
         "int"],
)  # fmt: skip
def test_any_other_value_under_bearer_is_masked(value: Any) -> None:
    state = {"bearer": value, "nested": {"bearer": value}, "listed": [{"bearer": value}]}
    masked = {"bearer": REDACTION_MARKER}
    assert redact(state) == masked | {"nested": masked, "listed": [masked]}


def test_the_flag_words_pass_under_no_other_secret_name() -> None:
    state = {"token": "matched", "authorization": "absent", "bearer_token": "matched"}
    assert redact(state) == dict.fromkeys(state, REDACTION_MARKER)


def test_the_table_is_one_key_and_its_two_words_closed_and_read_only() -> None:
    """Review BK11-R2-CR-01: the closed set itself, read through the module."""
    table = redact_module._ENUM_PASS_THROUGH
    assert isinstance(table, MappingProxyType)
    assert dict(table) == {"bearer": frozenset({"matched", "absent"})}
    assert all(type(words) is frozenset for words in table.values())
