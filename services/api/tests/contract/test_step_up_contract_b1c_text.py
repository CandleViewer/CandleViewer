"""Contract text (E27-S04, #898, B1c): the account `ETag` and the `412` order, the four challenge
templates, the repeat and empty PATCH rules, `flatten_first` on a non-last key, the revoke's ahead
and completion records and the WebSocket narrowing on revoke or disable. Text only: no schema
member changes."""

from __future__ import annotations

from pathlib import Path

from tests.contract._admin_support import SPEC, text

_ROOT = Path(__file__).resolve().parents[4]
_RAW_23 = (_ROOT / "docs/plan/23-ws-protocol.md").read_text(encoding="utf-8")
_RAW_24 = (_ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
_DOC_24 = text(_RAW_24)
_NARROWING = "**A revoked key or a disabled account (E27-S04).**"
_TARGET = (
    "`target` is the account's label, or its id where `Problem.target`'s rule says so (not"
    " unique among the caller's visible accounts, or not printable ASCII)"
)
_ACCOUNT = "/exchange-accounts/{accountId}"
_KEY = "/exchange-accounts/{accountId}/keys/{keyId}"


def _op(path: str, method: str) -> str:
    return text(SPEC["paths"][path][method]["description"])


def _paragraph(raw: str, opening: str) -> str:
    """The one paragraph of `raw` that starts with `opening`, up to the next blank line."""
    start = raw.index(opening)
    end = raw.find("\n\n", start)
    return text(raw[start : end if end != -1 else len(raw)])


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
    assert "Without `If-Match` the request proceeds, last write wins" in text(patch["description"])


def test_the_four_challenges_name_their_template_and_target() -> None:
    patch, delete = _op(_ACCOUNT, "patch"), _op(_ACCOUNT, "delete")
    revoke = _op(_KEY, "delete")
    suffix = "'<label>' (<environment>, UID <exchange_uid>)"
    assert f"`Disable account {suffix}`, ending with `, open_exposure=<choice>`" in patch
    assert f"and {_TARGET}. For a re-enable" in patch
    assert f"`Re-enable account {suffix}`, with no suffix, and `target` is null" in patch
    assert "A re-enable ignores `open_exposure`: the choice applies only to disabling" in patch
    assert f"`Delete account {suffix}`" in delete
    assert _TARGET in delete
    assert "`Revoke key '<keyId>' of account " + suffix + "`" in revoke
    assert "`target` is null" in revoke


def test_a_repeated_disable_is_200_with_no_record_and_an_empty_patch_is_422() -> None:
    patch = SPEC["paths"][_ACCOUNT]["patch"]
    desc = text(patch["description"])
    assert "answers `200` with the account unchanged and writes no `account.disabled` /" in desc
    assert "`account.updated` record, beyond the step-up's own" in desc
    assert "is audited as any account update (`account.updated`)" in desc
    named = "names none of `label`, `enabled`, `position_mode`, `margin_mode`"
    assert f"A body that {named} is `422 validation_failed` (rule `empty_patch`)" in desc
    assert named in text(patch["responses"]["422"]["description"])
    example = patch["responses"]["422"]["content"]["application/problem+json"]["examples"]
    assert example["emptyPatch"]["value"]["errors"][0]["rule"] == "empty_patch"
    assert example["emptyPatch"]["value"]["code"] == "validation_failed"


def test_a_repeated_disable_reads_no_exposure_and_ignores_open_exposure() -> None:
    patch = _op(_ACCOUNT, "patch")
    assert (
        "A repeat reads no exposure and flattens nothing: `open_exposure` on it is ignored" in patch
    )


def test_a_stale_if_match_is_412_before_the_gate_and_again_before_any_flatten() -> None:
    patch = _op(_ACCOUNT, "patch")
    assert (
        "the tag is compared after the `404` and before the step-up gate, like the `422`" in patch
    )
    assert "a stale tag is `412`, spends no code and reads no exposure" in patch
    assert "taken before the `flatten_first` flatten starts and held until the write" in patch
    assert "decided before any close or flatten effect, and nothing changes" in patch
    assert "that second `412` comes after the gate and leaves the grant spent" in patch


def test_the_account_etag_can_be_built_from_the_body() -> None:
    header = text(SPEC["components"]["headers"]["AccountETag"]["description"])
    assert "render `updated_at` in the body with exactly six fractional digits" in header
    assert "the same formatter as the header (B4c)" in header
    assert "opaque" not in header


def test_flatten_first_on_a_non_last_key_is_a_recorded_no_op_answering_204() -> None:
    revoke = _op(_KEY, "delete")
    assert (
        "recorded no-op (the completion record `api_key.revoked` carries `flattened: false`"
        in revoke
    )
    assert "reason `other_key_signable`) and the revoke answers `204`" in revoke
    assert "still spends the `accounts` code" in revoke
    shared = text(SPEC["components"]["parameters"]["OpenExposure"]["description"])
    assert "only when the revoked key is the account's last signable key" in shared


def test_the_ahead_record_carries_intent_and_the_completion_record_says_flattened() -> None:
    revoke = _op(_KEY, "delete")
    assert "`api_key.revoke` is the ahead record (C-2.9): it carries only the decided" in revoke
    assert (
        "record `api_key.revoked` follows (`outcome: success`, severity `warning`), carrying"
        in revoke
    )
    assert (
        "`flattened` (`true` or `false`, with reason `other_key_signable` for the no-op)" in revoke
    )
    assert (
        "When the flatten acts but the revoke then fails, no completion record is written" in revoke
    )
    record = _paragraph(_RAW_24, "`api_key.revoke` is the ahead record of a revoke")
    assert "it carries only the decided intent, the `open_exposure` choice" in record
    assert "it carries `flattened` (`true` or `false`;" in record
    assert (
        "When the flatten acts but the revoke then fails, no `api_key.revoked` is written" in record
    )
    assert "the ahead record stands" in record
    assert "the ahead record says whether it acted" not in _DOC_24


def test_the_revoke_completion_record_is_in_the_vocabulary_after_its_ahead_record() -> None:
    assert (
        "`api_key.revoke`, `api_key.revoked` (not registered yet, B3), `apikey.verify_failed`"
        in _DOC_24
    )
    assert "`api_key.revoked` is its completion record" in _DOC_24
    assert "written after the key is destroyed and the close of its private streams" in _DOC_24
    assert "`api_key.revoked`" in _op(_KEY, "delete")


def test_revoke_and_disable_narrow_every_account_scoped_stream() -> None:
    revoke = _op(_KEY, "delete")
    narrowing = _paragraph(_RAW_23, _NARROWING)
    for topic in ("orders", "positions", "executions", "wallet", "trade_groups", "rules"):
        assert f"`{topic}`" in revoke
        assert f"`{topic}`" in narrowing
    machines = "`machines.{order|leg|algo|risk_lockout}.state`"
    assert machines in revoke
    assert f"The account's {machines} subscriptions end with the same reason" in narrowing
    assert "`permission_change` is sent first, then the narrowing" in narrowing


def test_resubscribe_allowed_follows_section_7_per_case() -> None:
    narrowing = _paragraph(_RAW_23, _NARROWING)
    assert (
        "a subscription left with no accounts ends with `resubscribe_allowed: false`" in narrowing
    )
    assert "keeps its other accounts and carries `resubscribe_allowed: true`" in narrowing
    assert "is refused for it with `account_scope_denied`" in narrowing
    assert "until the key is replaced (`key_revoked`) or the account re-enabled" in narrowing
    assert "`false` for the removed account" not in narrowing
    assert "after which a new `sub` is allowed" not in narrowing


def test_a_disable_names_the_temporary_account_disabled_close_a_re_enable_lifts() -> None:
    patch = _op(_ACCOUNT, "patch")
    assert (
        "temporary reason `account_disabled` (joins 24 §14.2 rule 13 and §14.4 with B4a)" in patch
    )
    assert (
        "a re-enable lifts that reason and the streams reopen on the account's signable keys"
        in (patch)
    )
