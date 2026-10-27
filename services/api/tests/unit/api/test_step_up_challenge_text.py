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
    CreateExchangeAccountRequest,
    CreateUserRequest,
    KekRewrapRequest,
    RotateAuditSigningKeyRequest,
    UpdateUserRequest,
)
from candleviewer.api.step_up_challenge import (
    UPDATE_USER_RENDERED,
    account_reference,
    challenge_reason,
    export_audit_text,
    import_key_text,
    invite_user_text,
    kek_rewrap_text,
    pin_symbol_text,
    profile_write_text,
    quote_label,
    register_account_text,
    reissue_invite_text,
    retention_policies_text,
    revoke_invite_text,
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


def test_invite_recorder_profile_and_account_texts_restate_validated_values_only() -> None:
    """#2304 slice 3c: users, profiles and entries by id, an account by its reference, enums,
    counts and days bare; a username, email, display name or label is never an argument."""
    account = account_reference("Main", "demo", "1001234")
    texts = {
        invite_user_text(
            ["viewer"], mfa_required=True
        ): "Invite a new user as viewer (MFA required)",
        invite_user_text(["viewer"], mfa_required=False): (
            "Invite a new user as viewer (MFA not required)"
        ),
        reissue_invite_text("u1"): "Reissue the invite link of user u1",
        revoke_invite_text("u1"): "Revoke the pending invite of user u1",
        retention_policies_text(
            1, apply_now=False
        ): "Replace the retention policy set with 1 policy",
        retention_policies_text(9, apply_now=True): (
            "Replace the retention policy set with 9 policies, then sweep now"
        ),
        pin_symbol_text("BTCUSDT", "e1", pinned=True, retention_days=None): (
            "Pin the recording of BTCUSDT (keep forever)"
        ),
        pin_symbol_text("BTCUSDT", "e1", pinned=False, retention_days=7): (
            "Unpin the recording of BTCUSDT, keeping 7 days"
        ),
        pin_symbol_text("btc'usdt", "e1", pinned=False, retention_days=None): (
            "Unpin the recording of entry e1"
        ),
        profile_write_text("create", account): (
            "Create a risk profile for account 'Main' (demo, UID 1001234)"
        ),
        profile_write_text("replace", account, "p1"): (
            "Replace risk profile p1 of account 'Main' (demo, UID 1001234)"
        ),
        profile_write_text("delete", account, "p1"): (
            "Delete risk profile p1 of account 'Main' (demo, UID 1001234)"
        ),
        profile_write_text("default", account, "p1"): (
            "Make risk profile p1 the default of account 'Main' (demo, UID 1001234)"
        ),
        register_account_text("bybit", "live", "main", "1001234"): (
            "Register a main live bybit account, UID 1001234"
        ),
        register_account_text("bybit", "demo", "sub", "1001235", "a1"): (
            "Register a sub demo bybit account, UID 1001235 under account a1"
        ),
    }
    for text, summary in texts.items():
        assert (text.action_summary, text.target) == (summary, None)


def test_slice_3c_enum_texts_restate_every_value_of_their_generated_literal() -> None:
    """The allow-lists are the generated contract Literals (22 `CreateUserRequest.roles`,
    `CreateExchangeAccountRequest`): every contract value renders."""
    roles = get_args(get_args(CreateUserRequest.model_fields["roles"].annotation)[0])
    fields = CreateExchangeAccountRequest.model_fields
    kinds, envs = (get_args(fields[f].annotation) for f in ("kind", "environment"))
    assert roles and kinds and envs
    for role in roles:
        assert f" as {role} " in invite_user_text([role], mfa_required=True).action_summary
    for kind in kinds:
        for env in envs:
            summary = register_account_text("bybit", env, kind, "1001234").action_summary
            assert f"a {kind} {env} bybit account" in summary


@pytest.mark.parametrize(
    "build",
    [
        lambda: invite_user_text([_SENTINEL], mfa_required=True),
        lambda: register_account_text("bybit", "live", _SENTINEL, "1001234"),
        lambda: register_account_text("bybit", _SENTINEL, "main", "1001234"),
        lambda: register_account_text(_SENTINEL, "live", "main", "1001234"),
        lambda: register_account_text("bybit", "live", "main", _SENTINEL),
    ],
    ids=["invite-role", "account-kind", "account-environment", "exchange", "exchange-uid"],
)
def test_slice_3c_texts_refuse_a_value_outside_their_enum(build: Callable[[], object]) -> None:
    """Fail closed: a value the contract lacks is a defect, never restated."""
    with pytest.raises(ValueError):
        build()


#: The SCR-006 frame `no-grace-live-enable` (E09-D06), whose annotation reads "Same frame for
#: kill-switch disable": its line under the action, verbatim.
_NO_GRACE_WHY = (
    "Live enablement and kill-switch disable always need a fresh code, even right after a "
    "recent step-up."
)


@pytest.mark.parametrize("action_class", ["live_enablement", "killswitch"])
def test_challenge_reason_is_the_designed_no_grace_line(action_class: str) -> None:
    assert challenge_reason(action_class) == _NO_GRACE_WHY


@pytest.mark.parametrize(
    "action_class",
    ["keys", "users", "risk_caps", "recorder", "recorder_purge", "flags", "audit", "backups"],
)
def test_challenge_reason_is_omitted_for_a_class_with_no_designed_line(action_class: str) -> None:
    """No copy is invented (AGENTS.md §8.13): a class whose SCR-006 frame draws no reason of its
    own gets none."""
    assert challenge_reason(action_class) is None


def test_challenge_reason_is_none_for_an_unknown_class() -> None:
    assert challenge_reason("bogus") is None
