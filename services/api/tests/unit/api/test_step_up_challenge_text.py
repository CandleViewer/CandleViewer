"""#2304: the text a `403 step_up_required` restates its request with (pure helpers, no I/O).

`Problem.action_summary` names each account by its label, `environment` and `exchange_uid`,
and escapes every label so its quotes bound it; `Problem.target` is a label only when it is
printable ASCII and unique among the caller's visible objects. The oracle is the contract's own
(`tests/contract/test_step_up_challenge_contract.py`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.api._generated.openapi_models import (
    KekRewrapRequest,
    RotateAuditSigningKeyRequest,
    UpdateUserRequest,
)
from candleviewer.api.step_up_challenge import (
    UPDATE_USER_RENDERED,
    account_reference,
    export_audit_text,
    import_key_text,
    kek_rewrap_text,
    quote_label,
    rotate_signing_key_text,
    typed_target,
    update_user_text,
)
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


_SENTINEL = "SENTINEL-free-text-7731"


def test_update_user_text_renders_only_the_allow_listed_values() -> None:
    """#2304: every `UpdateUserRequest` field outside the allow-list is named, never valued,
    so free text (and any field the contract adds later) cannot reach the restatement."""
    assert UPDATE_USER_RENDERED <= set(UpdateUserRequest.model_fields)
    for field in set(UpdateUserRequest.model_fields) - UPDATE_USER_RENDERED:
        text = update_user_text("u1", {field: _SENTINEL}).action_summary
        assert _SENTINEL not in text and field.replace("_", " ") in text, field
    unknown = update_user_text("u1", {"some_new_field": _SENTINEL}).action_summary
    assert unknown == "Update user u1: some new field"


def test_update_user_text_renders_allow_listed_values_bare() -> None:
    change: dict[str, object] = {
        "roles": ["viewer", "manager"],
        "status": "disabled",
        "mfa_required": True,
        "display_name": _SENTINEL,
    }
    assert update_user_text("u1", change).action_summary == (
        "Update user u1: display name; mfa_required true; roles manager, viewer; status disabled"
    )


def test_key_kek_and_audit_texts_restate_validated_values_only() -> None:
    """#2304 slice 3b: an account by its reference, enums and instants bare; the pasted key pair,
    a key label and `expected_uid` are never arguments, so they cannot reach the text."""
    account = account_reference("Main", "demo", "1001234")
    assert import_key_text(account, read_only=True).action_summary == (
        "Import a read-only API key for account 'Main' (demo, UID 1001234)"
    )
    assert import_key_text(account, read_only=False).action_summary == (
        "Import a trading API key for account 'Main' (demo, UID 1001234)"
    )
    assert kek_rewrap_text("live", 3).action_summary == (
        "Re-wrap the live API keys under credential key version 3"
    )
    assert rotate_signing_key_text("compromise").action_summary == (
        "Rotate the audit export signing key (compromise)"
    )
    start = datetime(2026, 10, 1, 2, tzinfo=timezone(timedelta(hours=2)))
    text = export_audit_text(start, datetime(2026, 10, 2, tzinfo=UTC), compress=False)
    assert text.action_summary == (
        "Export the audit log from 2026-10-01T00:00:00+00:00 to 2026-10-02T00:00:00+00:00"
    )
    assert export_audit_text(start, start, compress=True).action_summary.endswith(", compressed")
    assert {t.target for t in (text, kek_rewrap_text("demo", 2))} == {None}


def test_enum_texts_restate_every_value_of_their_generated_literal() -> None:
    """#2304 slice 3b (review): the allow-lists are the generated contract Literals, so every
    contract value renders and nothing else does."""
    environments = get_args(KekRewrapRequest.model_fields["environment"].annotation)
    reasons = get_args(RotateAuditSigningKeyRequest.model_fields["reason"].annotation)
    assert environments and reasons
    assert all(isinstance(v, str) for v in environments + reasons)  # a bare Literal, never `| None`
    for environment in environments:
        assert f" {environment} " in kek_rewrap_text(environment, 2).action_summary
    for reason in reasons:
        assert rotate_signing_key_text(reason).action_summary.endswith(f"({reason})")


@pytest.mark.parametrize(
    "build",
    [lambda: kek_rewrap_text(_SENTINEL, 2), lambda: rotate_signing_key_text(_SENTINEL)],
    ids=["kek-environment", "signing-reason"],
)
def test_enum_texts_refuse_a_value_outside_their_enum(build: Callable[[], object]) -> None:
    """Fail closed: a value the contract's enum lacks is a defect, never restated."""
    with pytest.raises(ValueError):
        build()
