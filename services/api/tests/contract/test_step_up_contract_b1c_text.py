"""Contract text (E27-S04, #898, B1c): the account `ETag`, the four challenge templates, the repeat
and empty PATCH rules, `flatten_first` on a non-last key, the revoke completion record and the
WebSocket narrowing on revoke or disable. Text only: no schema member changes."""

from __future__ import annotations

from pathlib import Path

from tests.contract._admin_support import SPEC, text

_ROOT = Path(__file__).resolve().parents[4]
_DOC_23 = text((_ROOT / "docs/plan/23-ws-protocol.md").read_text(encoding="utf-8"))
_DOC_24 = text((_ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8"))
_ACCOUNT = "/exchange-accounts/{accountId}"
_KEY = "/exchange-accounts/{accountId}/keys/{keyId}"


def _op(path: str, method: str) -> str:
    return text(SPEC["paths"][path][method]["description"])


def test_the_account_etag_is_a_reusable_header_over_updated_at() -> None:
    header = SPEC["components"]["headers"]["AccountETag"]
    assert 'W/"<updated_at>"' in text(header["description"])
    assert "exactly six fractional digits" in text(header["description"])
    assert "\\.[0-9]{6}Z" in header["schema"]["pattern"]


def test_get_and_patch_answer_the_account_etag() -> None:
    ref = {"$ref": "#/components/headers/AccountETag"}
    assert SPEC["paths"][_ACCOUNT]["get"]["responses"]["200"]["headers"]["ETag"] == ref
    assert SPEC["paths"][_ACCOUNT]["patch"]["responses"]["200"]["headers"]["ETag"] == ref


def test_patch_if_match_stays_optional_and_a_stale_tag_is_412() -> None:
    patch = SPEC["paths"][_ACCOUNT]["patch"]
    assert {"$ref": "#/components/parameters/IfMatch"} in patch["parameters"]
    assert "412" in patch["responses"]
    assert "without it the request proceeds" in text(patch["description"])


def test_the_four_challenges_name_their_template_and_target() -> None:
    patch, delete = _op(_ACCOUNT, "patch"), _op(_ACCOUNT, "delete")
    revoke = _op(_KEY, "delete")
    suffix = "'<label>' (<environment>, UID <exchange_uid>)"
    assert f"`Disable account {suffix}` and `target` is the account's label" in patch
    assert f"`Re-enable account {suffix}` and `target` is null" in patch
    assert f"`Delete account {suffix}`" in delete
    assert "and `target` is the account's label" in delete
    assert "`Revoke key '<keyId>' of account " + suffix + "`" in revoke
    assert "`target` is null" in revoke


def test_a_repeated_disable_is_200_with_no_record_and_an_empty_patch_is_422() -> None:
    patch = SPEC["paths"][_ACCOUNT]["patch"]
    desc = text(patch["description"])
    assert "answers `200` with the account unchanged and writes no audit record" in desc
    assert "`422 validation_failed` (rule `empty_patch`), decided before the gate" in desc
    example = patch["responses"]["422"]["content"]["application/problem+json"]["examples"]
    assert example["emptyPatch"]["value"]["errors"][0]["rule"] == "empty_patch"
    assert example["emptyPatch"]["value"]["code"] == "validation_failed"


def test_flatten_first_on_a_non_last_key_is_a_recorded_no_op_answering_204() -> None:
    revoke = _op(_KEY, "delete")
    assert "recorded no-op (the record carries `flattened: false`, reason" in revoke
    assert "`other_key_signable`) and the revoke answers `204`" in revoke
    assert "still spends the `accounts` code" in revoke
    shared = text(SPEC["components"]["parameters"]["OpenExposure"]["description"])
    assert "only when the revoked key is the account's last signable key" in shared


def test_the_revoke_completion_record_is_in_the_vocabulary_after_its_ahead_record() -> None:
    assert "`api_key.revoke`, `api_key.revoked`, `apikey.verify_failed`" in _DOC_24
    assert "`api_key.revoked` is its completion record" in _DOC_24
    assert "written after the key is destroyed and the close of its private streams" in _DOC_24
    assert "`api_key.revoked`" in _op(_KEY, "delete")


def test_revoke_and_disable_narrow_every_account_scoped_stream() -> None:
    revoke = _op(_KEY, "delete")
    for topic in ("orders", "positions", "executions", "wallet", "trade_groups", "rules"):
        assert f"`{topic}`" in revoke
        assert f"`{topic}`" in _DOC_23.split("**A revoked key or a disabled account")[1][:600]
    assert "`permission_change` is sent first, then the narrowing" in _DOC_23
    assert "`resubscribe_allowed` is `false` for the removed account" in _DOC_23


def test_a_disable_names_the_temporary_account_disabled_close_a_re_enable_lifts() -> None:
    patch = _op(_ACCOUNT, "patch")
    assert "temporary reason `account_disabled`" in patch
    assert "a re-enable lifts that reason" in patch
