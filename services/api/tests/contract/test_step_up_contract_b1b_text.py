"""Contract text (E27-S04, #898, B1b): the `accounts` and `recorder_purge` step-up clauses, the
shared `If-Match` qualification and `updateRule`'s `400`, and the private-stream close and rotation
rules of 24 section 14.2 rule 13 with their 22 companions. Text only: no schema member changes."""

from __future__ import annotations

from pathlib import Path

from tests.contract._admin_support import SPEC, text

_DOC_24 = Path(__file__).resolve().parents[4] / "docs/plan/24-internal-schemas.md"


def _op(path: str, method: str) -> str:
    return text(SPEC["paths"][path][method]["description"])


def _action_class() -> str:
    body = SPEC["paths"]["/auth/step-up"]["post"]["requestBody"]["content"]["application/json"]
    return text(body["schema"]["properties"]["action_class"]["description"])


def _rule_13() -> str:
    doc = text(_DOC_24.read_text(encoding="utf-8"))
    start = doc.index("**Revocation and rotation (SR-E27-17, KV-E13).**")
    return doc[start : doc.index("**Connection budget", start)]


def test_the_accounts_class_is_e27_s04s_and_lands_in_slices_not_declared_ahead() -> None:
    clause = _action_class()
    assert (
        "the class and its routes are E27-S04's (#898), which lands them in slices (C-6.1)"
        in clause
    )
    assert "one fresh code per action; the class" in clause


def test_the_recorder_purge_class_is_tense_neutral() -> None:
    clause = _action_class()
    assert "a no-grace, request-bound class" in clause
    assert "E16-T06" not in clause
    assert "`recorder_purge` gates purging recorded data (`purgeRecordedData`)" in clause


def test_the_shared_if_match_names_where_the_header_is_required() -> None:
    shared = text(SPEC["components"]["parameters"]["IfMatch"]["description"])
    assert (
        "Omitting it accepts last-write-wins, except where an operation says it requires" in shared
    )
    assert "`updateRule` answers `400` without it" in shared
    assert SPEC["components"]["parameters"]["IfMatch"]["required"] is False


def test_update_rule_answers_400_without_a_version() -> None:
    rule = _op("/rules/{ruleId}", "put")
    assert "without `expected_version` in the body, the answer is `400`" in rule


def test_rule_13_answers_no_success_on_a_close_that_overruns() -> None:
    rule = _rule_13()
    assert "bounded at 2 s" in rule
    assert "answers no success" in rule
    assert "`PrivateStreamCloseOverran`" in rule
    assert "a retry is idempotent" in rule


def test_rule_13_switches_the_active_key_before_the_rotation_close() -> None:
    rule = _rule_13()
    assert "switched to the new key before the `key_rotated` close" in rule
    assert "refused with `AuthError`" in rule


def test_revoke_and_rotate_carry_the_private_stream_sentences() -> None:
    revoke = _op("/exchange-accounts/{accountId}/keys/{keyId}", "delete")
    assert "success only after the close of the key's private streams has completed" in revoke
    assert "an overrun is no success (`PrivateStreamCloseOverran`" in revoke
    rotate = _op("/exchange-accounts/{accountId}/keys/{keyId}/rotate", "post")
    assert "becomes the account's active key before the old key's streams are closed" in rotate
