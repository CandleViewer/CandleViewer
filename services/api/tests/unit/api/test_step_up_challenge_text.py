"""#2304: the text a `403 step_up_required` restates its request with (pure helpers, no I/O).

`Problem.action_summary` names each account by its label, `environment` and `exchange_uid`,
and escapes every label so its quotes bound it; `Problem.target` is a label only when it is
printable ASCII and unique among the caller's visible objects. The oracle is the contract's own
(`tests/contract/test_step_up_challenge_contract.py`).
"""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.api.step_up_challenge import account_reference, quote_label, typed_target
from tests.contract.test_step_up_challenge_contract import (
    _SPEC,
    _account_reference,
    _is_quoted_label,
)

_ESCAPE = re.compile(r"\\u\{([0-9A-F]{4,6})\}|\\(.)")


def _unquote(quoted: str) -> str:
    return _ESCAPE.sub(lambda m: chr(int(m[1], 16)) if m[1] else m[2], quoted[1:-1])


@pytest.mark.parametrize(
    ("label", "quoted"),
    [
        ("sub_002", "'sub_002'"),
        ("demo-1' (demo)", "'demo-1\\' (demo)'"),
        ("C:\\keys", "'C:\\\\keys'"),
        ("a\nb\u202ec\U0001f600", "'a\\u{000A}b\\u{202E}c\\u{1F600}'"),
        ("\u2019demo\u2019", "'\\u{2019}demo\\u{2019}'"),
        ("del\x7f", "'del\\u{007F}'"),
    ],
    ids=["plain", "apostrophe", "backslash", "control-bidi-emoji", "look-alike-quote", "del"],
)
def test_quote_label_escapes_as_the_contract_states(label: str, quoted: str) -> None:
    assert quote_label(label) == quoted


@given(st.text())
def test_any_quoted_label_is_bounded_by_its_quotes_and_names_one_label(label: str) -> None:
    quoted = quote_label(label)
    assert _is_quoted_label(quoted)
    assert _unquote(quoted) == label  # injective: two labels never read alike


def test_account_reference_names_the_account_beyond_its_label() -> None:
    reference = account_reference("sub_002", "live", "1001234")
    assert reference == "'sub_002' (live, UID 1001234)"
    assert _account_reference(_SPEC).fullmatch(reference)


@pytest.mark.parametrize(
    ("environment", "uid"), [("prod", "1001234"), ("live", "12a"), ("demo", "")]
)
def test_account_reference_refuses_an_unregistered_environment_or_uid(
    environment: str, uid: str
) -> None:
    with pytest.raises(ValueError, match="environment and UID"):
        account_reference("sub_002", environment, uid)


@pytest.mark.parametrize(
    ("label", "others", "target"),
    [
        ("sub_002", ["main", "sub_001"], "sub_002"),
        ("sub_002", ["main", "SUB_002"], "acc-7"),
        ("sub\u2019002", [], "acc-7"),
        ("sub\n002", [], "acc-7"),
    ],
    ids=["unique", "same-label-other-case", "not-ascii", "not-printable"],
)
def test_typed_target_is_a_unique_printable_label_else_the_identifier(
    label: str, others: list[str], target: str
) -> None:
    assert typed_target(label, "acc-7", others) == target
