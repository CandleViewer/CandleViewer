"""The limiter/budget/verify defaults must match the merged contract text (#2392). E42-T02 S2 (#889,
ADR-0039) pins the export's limits, the signing-key list and the manifest's key below."""

from __future__ import annotations

import base64
import functools
import hashlib
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from candleviewer.api._generated import openapi_models as api
from candleviewer.audit.query import HASHED_FIELDS
from candleviewer.audit.redact import REDACTION_MARKER, redact
from candleviewer.settings import Settings
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.contract._admin_support import OWNER_ONLY, ROOT, SPEC, example_cases, text
from tests.contract._admin_support import validate_example as validate

_SPEC = Path(__file__).resolve().parents[4] / "docs" / "plan" / "22-api-openapi.yaml"


def test_settings_defaults_are_named_in_the_contract() -> None:
    text = _SPEC.read_text(encoding="utf-8")
    missing = [
        name
        for name in (
            "audit_query_rate_per_minute",
            "audit_query_max_concurrent",
            "audit_query_timeout_ms",
            "audit_record_budget_per_hour",
            "audit_record_budget_owner_per_hour",
            "audit_read_flush_pages",
            "audit_read_flush_seconds",
            "audit_budget_tracked_users",
            "audit_inflight_writes",
            "audit_verify_max_span",
            "audit_verify_rate_per_hour",
            "audit_verify_deadline_s",
            "audit_verify_statement_timeout_ms",
            "audit_verify_max_entry_bytes",
            "view_as_refusal_budget_per_hour",  # #3085: the view-as refusals' own cap
            "rules_refusal_budget_per_hour",  # #4834: the rule routes' refusal records' cap
        )
        if name not in text
    ]
    assert not missing, (
        f"contract PR #2392 is not in this base: {missing} absent from 22-api-openapi.yaml; "
        "merge #2392 first (contract-first)"
    )
    s = Settings()
    assert (s.audit_query_rate_per_minute, s.audit_query_max_concurrent) == (60, 2)
    assert (s.audit_query_timeout_ms, s.audit_record_budget_per_hour) == (4000, 120)
    assert (s.audit_record_budget_owner_per_hour, s.audit_read_flush_pages) == (600, 50)
    assert (s.audit_read_flush_seconds, s.audit_budget_tracked_users) == (300.0, 1024)
    assert (s.audit_inflight_writes, s.audit_verify_max_span) == (64, 1_000_000)
    assert s.audit_verify_rate_per_hour == 30
    assert (s.audit_verify_deadline_s, s.audit_verify_statement_timeout_ms) == (60.0, 10_000)
    assert s.audit_verify_max_entry_bytes == 4_194_304  # 4 MiB
    assert s.view_as_refusal_budget_per_hour == 120
    assert s.rules_refusal_budget_per_hour == 120


def test_view_as_refusal_cap_default_is_the_one_the_contract_states() -> None:
    """#3085: "View-as session" names the refusal records' own hourly cap with its default; a
    drift on either side fails here."""
    text = " ".join(_SPEC.read_text(encoding="utf-8").split())
    stated = re.search(r"`view_as_refusal_budget_per_hour` \(default (\d+)\)", text)
    assert stated, "the View-as session section no longer states the cap's default"
    assert Settings.model_fields["view_as_refusal_budget_per_hour"].default == int(stated[1])


def _verify_limits() -> str:
    """The `**Limits.**` paragraph of `verifyAuditChain`, on one line."""
    text = _SPEC.read_text(encoding="utf-8")
    section = text.split("operationId: verifyAuditChain", 1)[1].split("x-rbac:", 1)[0]
    assert "**Limits.**" in section, "the verify section no longer has a Limits paragraph"
    return " ".join(section.split("**Limits.**", 1)[1].split())


def test_verify_limit_defaults_are_the_ones_the_contract_states() -> None:
    """F14-1: the verify section states a default for each of the three limits, in its own
    unit, and each is the `Settings` default: a drift on either side fails here."""
    limits, unit = _verify_limits(), {None: 1, " s": 1, " MiB": 1024 * 1024}
    for name in (
        "audit_verify_deadline_s",
        "audit_verify_statement_timeout_ms",
        "audit_verify_max_entry_bytes",
    ):
        stated = re.search(rf"`{name}`,? \(?default (\d+)( s| MiB)?\)", limits)
        assert stated, f"the verify section no longer states a default for {name}"
        assert Settings.model_fields[name].default == int(stated[1]) * unit[stated[2]]


# -- E42-T02 S2 (#889, ADR-0039): contract-first; S4 to S10 build what these pin -----------------

_KEYS = "/admin/audit/signing-keys"
_LIST: dict[str, Any] = SPEC["paths"][_KEYS]["get"]
_EXPORT = text(SPEC["paths"]["/admin/audit/export"]["post"]["description"])
_TESTS = ROOT / "services/api/tests"
_MATRIX = yaml.safe_load((_TESTS / "contract/rbac/matrix.yaml").read_text(encoding="utf-8"))
_EXAMPLES = example_cases([(_KEYS, "get"), ("/admin/jobs/{jobId}", "get")])
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]


@functools.cache
def _format() -> str:
    """24 §15.7, read on a test's first call: renumbering it fails only the tests that read it."""
    doc = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
    return doc.split("\n### 15.7 ", 1)[1].split("\n---\n", 1)[0]


def _example(path: str, name: str) -> Any:
    (value,) = [v for case, _, v in _EXAMPLES if case == f"get {path} 200 {name}"]
    return value


def test_export_limits_are_settings_named_with_their_defaults() -> None:
    for name, default in (
        ("audit_export_max_range_days", 31),
        ("audit_export_max_rows", 1_000_000),
        ("audit_export_max_bytes", 1_073_741_824),  # 1 GiB, the file as written
        ("audit_export_ttl_s", 86_400),
    ):
        stated = re.search(rf"`{name}`[^(]*\(default (\d+)\)", _EXPORT)
        assert stated and int(stated[1]) == default, name
        assert name not in Settings.model_fields or Settings.model_fields[name].default == default
    rate = re.search(r"\(`audit_export_rate_per_hour`, default (\d+);", _EXPORT)  # #889 S10
    lookup = "`409 idempotency_key_reuse`, before any refusal below; `503 signing_unavailable`;"
    assert lookup in _EXPORT  # the route answers the stored `202` ahead of every refusal (S10b)
    assert rate and Settings.model_fields["audit_export_rate_per_hour"].default == int(rate[1]) == 5
    assert Settings.model_fields["audit_export_max_range_days"].default == 31


def test_the_download_limit_is_a_setting_with_the_default_the_contract_states() -> None:
    """#889 S9: `downloadAuditExport` names `audit_download_rate_per_hour` with its default."""
    download = text(SPEC["paths"]["/admin/audit/exports/{jobId}"]["get"]["description"])
    stated = re.search(r"`audit_download_rate_per_hour` \(default (\d+)\)", download)
    assert stated and Settings.model_fields["audit_download_rate_per_hour"].default == int(
        stated[1]
    )


@pytest.mark.parametrize(
    "rule",
    [
        "none while a signing-key rotation runs for the environment (`409 conflict`)",
        "a request is answered `503 signing_unavailable` and no job is created",
        "after validation (`422`) and before `429`, `409` and the write-ahead request record",
        "That check reads M2's degraded state and opens no seed",
        "recorded as `admin.audit_denied` with reason `signing_unavailable` under the audit budget",
        "never `audit_export_rate_per_hour` quota, and carries no `Retry-After` unless that",
        "fails with `error: export_too_large` too and leaves nothing on disk",
        "fails unsigned with `error: signing_key_rotated`",
        "a write-ahead `admin.audit_export` record with reason `downloaded`",
        "Completion is audited with the job id",
    ],
)
def test_export_states_the_adr_0039_rule(rule: str) -> None:
    assert rule in _EXPORT


def test_export_is_served_with_no_501_and_its_checks_in_one_order() -> None:
    """#889 S10b replaced the `501` with the route: the operation declares none, and states its
    checks in this order, the idempotency lookup before every refusal that follows validation.
    #2304 slice 3b: the step-up follows authentication, RBAC and validation, never before."""
    export = SPEC["paths"]["/admin/audit/export"]["post"]
    assert set(export["responses"]) == {"202", "401", "403", "409", "422", "429", "503"}
    assert "Not implemented yet" not in _EXPORT and "not_implemented" not in _EXPORT
    order = _EXPORT.split("**Order of the checks**", 1)[1].split("**Who.**", 1)[0]
    cues = [
        "`401`", "`403` (`code: forbidden`)", "validation (`422`", "`403 step_up_required`",
        "the idempotency lookup", "`503 signing_unavailable`;", "rate limit (`429`)",
        "single-flight (`409 conflict`)", "the write-ahead request record and the `202`",
    ]  # fmt: skip
    at = [order.index(cue) for cue in cues]
    assert at == sorted(at)
    assert "the `429` and the two `409`s (`conflict` and `idempotency_key_reuse`) are" in order
    assert "Only an export whose job is created counts toward the hourly rate" in order
    assert "so a caller these checks refuse is never challenged" in order


def test_export_is_unavailable_too_while_its_directory_takes_no_hard_links() -> None:
    """#889 S9-2's probe (`links_ok`), consumed by S10: refused as the key's check is, recorded
    with a reason of its own, and a sweep probes again."""
    rule = "The same check answers the same way while the export directory takes no hard links"
    assert rule in _EXPORT and "recorded with reason `export_volume_unavailable`" in _EXPORT
    assert "the sweep probes again every 60 s, so a remount recovers with no restart" in _EXPORT


def test_signing_unavailable_names_no_kek_among_a_failed_jobs_causes() -> None:
    job_error = text(_SCHEMAS["Job"]["properties"]["error"]["description"])
    assert "`signing_unavailable` (no KEK held, no usable key or a key that cannot be" in job_error


def test_signing_unavailable_is_a_registered_rest_only_503() -> None:
    """Its title names both causes the export route answers it for: the key, and an export
    directory that takes no hard links (#889 S10, the security lens's C1-1)."""
    (entry,) = [e for e in SPEC["x-error-codes"] if e["code"] == "signing_unavailable"]
    assert (entry["status"], entry["retryable"]) == (503, False)
    assert "or the export directory takes no hard links" in entry["title"]
    assert ERROR_META[ErrorCode("signing_unavailable")].surfaces == ("rest",)


def test_an_exports_key_is_kept_with_its_job_not_for_24_h() -> None:
    """The export's `Idempotency-Key` lives with its job in the process's job store, as the
    recorder's job routes keep theirs, never for the 24 h the global rule states (ruling,
    2026-10-23; the security lens's C1-2)."""
    info = text(SPEC["info"]["description"])
    assert "It keeps that `202` with its job in the process's job store, as" in info
    assert "all lost at a restart, so for no fixed 24 h." in info


def test_a_job_succeeds_only_once_its_completion_is_recorded() -> None:
    """#889 S10 (the code lens's C1-1): an unwritten completion fails the job `audit_unavailable`
    and removes its file; **Audit** names `admin.audit_export`'s four reasons."""
    job_error = text(_SCHEMAS["Job"]["properties"]["error"]["description"])
    assert "or the export's completion record could not be written, and its file is" in job_error
    audit = _EXPORT.split("**Audit.**", 1)[1]
    assert "The job turns `succeeded` only once its completion `admin.audit_export` is" in audit
    assert "`requested`, `completed` and `failed`, beside the download's `downloaded`." in audit


def test_the_file_format_says_s10b_schedules_the_export() -> None:
    """24 §15.7 (the code lens's C1-4): the job replaced the `501` in S10b."""
    assert "since S10b replaced its `501`, `exportAuditLog` schedules the job that" in _format()


def test_job_error_names_every_code_a_failed_export_carries() -> None:
    job_error = text(_SCHEMAS["Job"]["properties"]["error"]["description"])
    assert "A failed `audit_export` job has produced no downloadable file" in job_error
    codes = ("export_too_large", "signing_key_rotated", "signing_unavailable", "audit_unavailable")
    assert [code for code in [*codes, "internal_error"] if f"`{code}`" not in job_error] == []


def test_signing_key_list_is_an_audit_read_for_the_owner_only_as_verify_is() -> None:
    verify = SPEC["paths"]["/admin/audit/verify"]["post"]
    assert _LIST["operationId"] == "listAuditSigningKeys"
    assert _LIST["x-rbac"] == verify["x-rbac"] == {"permissions": ["audit:read"], "scope": "none"}
    assert set(_LIST["responses"]) == {"200", "401", "403", "429", "503"}
    outcomes = {key: row["outcomes"] for key, row in _MATRIX["operations"].items()}
    assert outcomes[f"GET {_KEYS}"] == OWNER_ONLY == outcomes["POST /admin/audit/verify"]
    desc = text(_LIST["description"])
    assert "Owner only (`04-security-program.md` §7.2.2 row 49b), as `verifyAuditChain` is" in desc
    assert "a Manager holding `audit:read` is refused with `403`" in desc


def test_signing_key_list_is_a_budgeted_audit_read_that_names_no_step_up_and_no_anchor() -> None:
    desc = text(_LIST["description"])
    assert 'one filter set of its own, `{"view": "signing_keys"}`, which no `queryAuditLog`' in desc
    assert "its `admin.audit_read` names `object_kind` `audit_signing_key`" in desc
    assert "never from this list or a rotation's `200`" in desc and "§15.7" in desc
    assert not re.search(r"step[-_ ]up", desc, re.IGNORECASE)  # a read: the sweep skips it


def test_signing_key_is_public_material_only() -> None:
    key = _SCHEMAS["AuditSigningKey"]
    assert key["additionalProperties"] is False
    assert set(key["required"]) == set(key["properties"]) == set(api.AuditSigningKey.model_fields)
    assert not [name for name in key["properties"] if re.search(r"seed|private|secret", name)]


def test_a_rotation_may_retire_an_unrecoverable_key_as_after_a_kek_loss() -> None:
    reasons = ["scheduled", "compromise", "unrecoverable"]
    request = _SCHEMAS["RotateAuditSigningKeyRequest"]["properties"]["reason"]["enum"]
    retired = _SCHEMAS["AuditSigningKey"]["properties"]["retired_reason"]["enum"]
    assert (request, retired) == (reasons, [*reasons, None])
    api.RotateAuditSigningKeyRequest.model_validate({"reason": "unrecoverable"})


def test_manifest_requires_the_public_key_the_header_also_carries() -> None:
    result = SPEC["components"]["schemas"]["AuditExportResult"]
    assert "public_key" in result["required"] and "public_key" in api.AuditExportResult.model_fields
    assert result["properties"]["public_key"]["pattern"] == "^[A-Za-z0-9+/]{43}=$"  # 32 bytes
    assert "the first key's generation record" in text(result["description"])


def test_examples_sign_the_versioned_digest_and_derive_every_key_id_from_the_fingerprint() -> None:
    """ADR-0039 decision 1, with RFC 8032 §7.1 TEST 1 and 2 keys: an executable pin of the
    message `cv.audit.export.v1:` + hex SHA-256, and of `key_id` = version + 16 hex."""
    done = _example("/admin/jobs/{jobId}", "done")["result"]
    message = f"cv.audit.export.v1:{done['sha256']}".encode("ascii")
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(done["public_key"]))
    key.verify(base64.b64decode(done["signature"]), message)  # raises if the pin drifted
    for item in [done, *_example(_KEYS, "rotatedOnce")["items"]]:
        fingerprint = hashlib.sha256(base64.b64decode(item["public_key"])).hexdigest()
        assert item["key_id"].endswith(f":{fingerprint[:16]}")
        assert item.get("fingerprint_sha256", fingerprint) == fingerprint


@pytest.mark.parametrize(("case", "pointer", "value"), _EXAMPLES, ids=[c[0] for c in _EXAMPLES])
def test_signing_key_and_job_examples_validate(case: str, pointer: str, value: Any) -> None:
    validate(pointer, value)


def test_the_file_format_pins_the_message_the_header_and_entry_members_and_five_checks() -> None:
    """24 §15.7: the 83-byte message, the header's 12 members (`from` and `to` equal to the
    manifest's as instants), an entry's 21 members (the columns `audit_chain()` hashes, the row's
    own and `in_window`, sorted) and the five verification steps."""
    prefix, section = "cv.audit.export.v1:", _format()
    assert f"the {len(prefix) + 64} ASCII bytes `{prefix}`" in section  # + the hex SHA-256
    header = re.sub(r"\([^()]*\)", "", section.split("**Header.** ", 1)[1].split("\n", 1)[0])
    named = ["format", "environment", "from", "to", "first_id", "last_id", "anchor_hash"]
    named += ["head_id", "head_hash", "row_count", "key_id", "public_key"]
    assert re.findall(r"`([a-z_]+)`", header.split(". ", 1)[0]) == named
    assert "`from` and `to` equal the manifest's as instants, and `first_id`" in header
    listed = section.split("21 members, in the order they are written: ", 1)[1].split(".", 1)[0]
    own = {"id", "prev_hash", "entry_hash", "record_id", "object_label", "in_window"}
    assert re.findall(r"`([a-z_]+)`", listed) == sorted({*HASHED_FIELDS, *own})
    steps = dict(re.findall(r"^(\d)\. (.*)$", section, re.MULTILINE))
    assert list(steps) == ["1", "2", "3", "4", "5"] and "as instants, not as" in steps["4"]
    assert steps["2"].startswith("In the header, `key_id` and `public_key` equal the manifest's;")


def test_every_copy_of_the_pin_rule_pins_only_from_a_rotation_the_owner_performed() -> None:
    """ADR-0039 decision 4: a key is pinned from a rotation the Owner performed, or the first
    key's generation record; a rotation record the Owner did not perform is an incident."""
    rotate = SPEC["paths"]["/admin/keys/audit-signing/rotate"]["post"]
    schemas = [_SCHEMAS["AuditExportResult"], _SCHEMAS["AuditSigningKey"]]
    copies = [_LIST, rotate, rotate["responses"]["200"], *schemas]
    for copy in [text(c["description"]) for c in copies] + [_format()]:
        assert "a rotation the Owner performed (matched to the Owner's own request)" in copy
    for copy in (text(_LIST["description"]), text(rotate["description"]), _format()):
        assert "`rotated` record the Owner did not perform is an incident, not a pin, until" in copy
    assert "can add that record, or a rotation or generation record (AD-T02)" in _format()


def test_the_rotation_and_signing_records_name_only_members_the_audit_redactor_keeps() -> None:
    """`redact()` erases a member named like a secret (`seed`, `hash`, `signature`, a `_key`
    suffix, so `public_key` too): every member the contract names for the rotated, failed and
    signing records, parsed from its text so that a member added later is covered, passes."""
    rotation = text(SPEC["paths"]["/admin/keys/audit-signing/rotate"]["post"]["description"])
    for where, start, end in (
        (rotation, "It names the acting Owner, the environment, ", "(names the audit redactor"),
        (rotation, "`security.audit_signing_key_rotation_failed`, naming ", ", which voids"),
        (_format(), "`audit_signing_key`, before every signature, naming ", "(S6 confirms)"),
    ):
        members = re.findall(r"`([a-z0-9_]+)(?::[^`]*)?`", where.split(start, 1)[1].split(end)[0])
        record = dict.fromkeys(members, "39f713d0a644253f")
        assert len(members) >= 2 and redact(record) == record, members
    assert redact({"public_key": "PUAX"}) == {"public_key": REDACTION_MARKER}
