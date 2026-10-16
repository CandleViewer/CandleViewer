"""Contract (E42-T03, contract slice): `GET /admin/feature-flags` and
`PUT /admin/feature-flags/{flagKey}` state the rules the flag service enforces, and every decision
is pinned by its full sentence, so a mutated rule fails here: resolution and the fail-closed
answer (D1), no overrides on safety flags at resolution or on write (D2), one step-up class per
write (D3), what maintenance mode refuses (D5), the push (D6) and the write semantics (D7). The
change is additive only (C-6.3): `SetFeatureFlagRequest` still requires only `value` and stays
closed, the list gains an optional `resolution`, and the PUT gains `401`/`404`/`409`/`503`."""

from __future__ import annotations

import re
from typing import Any

import pytest

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import REPO_ROOT, load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS

_SPEC = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_LIST = _SPEC["paths"]["/admin/feature-flags"]["get"]
_PUT = _SPEC["paths"]["/admin/feature-flags/{flagKey}"]["put"]
_REQUEST = _SCHEMAS["SetFeatureFlagRequest"]
_CODES = {entry["code"] for entry in _SPEC["x-error-codes"]}
_DOCS = REPO_ROOT / "docs" / "plan"


def _ref(name: str, kind: str = "schemas") -> dict[str, str]:
    return {"$ref": f"#/components/{kind}/{name}"}


def _text(description: str) -> str:
    return " ".join(description.split())


_GET_TEXT = _text(_LIST["description"])
_PUT_TEXT = _text(_PUT["description"])


def _list_example(name: str) -> dict[str, Any]:
    examples = _LIST["responses"]["200"]["content"]["application/json"]["examples"]
    value: dict[str, Any] = examples[name]["value"]
    return value


def test_put_documents_every_refusal_the_service_returns() -> None:
    assert set(_PUT["responses"]) == {"200", "401", "403", "404", "409", "422", "503"}
    assert set(_LIST["responses"]) == {"200", "401", "403"}


def test_conflict_answer_carries_the_current_flag() -> None:
    content = _PUT["responses"]["409"]["content"]["application/problem+json"]
    assert content["schema"] == _ref("FeatureFlagConflict")
    problem, extra = _SCHEMAS["FeatureFlagConflict"]["allOf"]
    assert problem == _ref("Problem")
    assert extra["required"] == ["current"]
    assert extra["properties"]["current"] == _ref("FeatureFlag")


def test_no_idempotency_key_so_every_409_is_a_conflict_with_current() -> None:
    assert _PUT["x-idempotency"] == "ignored"
    assert (
        "No `Idempotency-Key` is accepted: the precondition already makes a retry safe, so a "
        "`409` here is always `conflict` with `current`."
    ) in _PUT_TEXT


def test_request_change_is_additive_only() -> None:
    props = _REQUEST["properties"]
    assert _REQUEST["required"] == ["value"]
    assert _REQUEST["additionalProperties"] is False
    assert {k: props["reason"][k] for k in ("type", "maxLength")} == {
        "type": "string",
        "maxLength": 280,
    }
    assert props["evidence_url"]["format"] == "uri"
    assert props["expected_updated_at"]["type"] == "string"
    assert props["expected_updated_at"]["format"] == "date-time"
    assert set(props) == {"value", "overrides", "reason", "evidence_url", "expected_updated_at"}


@pytest.mark.parametrize(
    "code",
    ["validation_failed", "step_up_required", "conflict", "not_found", "store_unavailable"],
)
def test_every_error_code_the_rules_name_is_registered(code: str) -> None:
    assert code in _CODES
    assert f"`{code}`" in _PUT["description"] or f" {code}`" in _PUT["description"]


@pytest.mark.parametrize(
    "rule",
    [
        "required",
        "kind_mismatch",
        "unknown_user",
        "gate_evidence_required",
        "https_required",
        "overrides_not_allowed",
    ],
)
def test_validation_rules_are_named(rule: str) -> None:
    assert f"(rule `{rule}`)" in _PUT_TEXT or f"with rule `{rule}`" in _PUT_TEXT


def test_flags_change_is_named_and_registered() -> None:
    """`maintenance.enabled|disabled` are registered by the registry slice, not here."""
    assert (
        "audited as `flags.change` with the key, before, after, `reason` and `evidence_url`, "
        "including refused and conflicting ones."
    ) in _PUT_TEXT
    assert "flags.change" in AUDIT_ACTIONS


def test_generated_models_mirror_the_new_shapes() -> None:
    problem_fields = set(api.Problem.model_fields)
    assert set(api.FeatureFlagConflict.model_fields) == problem_fields | {"current"}
    assert set(api.SetFeatureFlagRequest.model_fields) == set(_REQUEST["properties"])
    assert "unreadable" in api.FeatureFlag.model_fields


def test_request_example_round_trips_without_field_loss() -> None:
    body = _PUT["requestBody"]["content"]["application/json"]["examples"]["enableLive"]["value"]
    model = api.SetFeatureFlagRequest.model_validate(body)
    assert model.model_dump(mode="json", exclude_unset=True) == body


def test_conflict_example_round_trips_without_field_loss() -> None:
    content = _PUT["responses"]["409"]["content"]["application/problem+json"]
    example = content["examples"]["staleRead"]["value"]
    model = api.FeatureFlagConflict.model_validate(example)
    assert model.model_dump(mode="json", exclude_unset=True) == example
    assert model.code == "conflict"
    assert model.status == 409


def test_maintenance_flags_are_catalogued_with_their_deployment_defaults() -> None:
    text = (_DOCS / "21-database-schema.md").read_text(encoding="utf-8")
    rows = {
        line.split("|")[1].strip(): [c.strip() for c in line.split("|")[2:5]]
        for line in text.splitlines()
        if line.startswith("| `maintenance.")
    }
    assert rows["`maintenance.mode`"][:2] == ["boolean", "`false`"]
    assert "is_killswitch=true" in rows["`maintenance.mode`"][2]
    assert rows["`maintenance.keep_recorder`"][:2] == ["boolean", "`true`"]


def test_definitions_never_gate_the_denied_categories() -> None:
    assert (
        "a flag may gate a UI surface or an incomplete feature, never authentication, RBAC "
        "enforcement, audit writing, the native-SL invariant, withdrawal permission or rate "
        "limiting (C-4.14), and the service refuses to start with a definition that declares one "
        "of them."
    ) in _GET_TEXT


# --- D1: resolution, and the observable answer when the store is unreachable -------------------


def test_d1_resolution_order_and_percentage_override_semantics() -> None:
    assert (
        "Resolution (E42-T03) is server-side only, per caller: user override, then role override, "
        "then percentage rollout (`hash(user_id || flag_key)`), then the deployment default"
    ) in _GET_TEXT
    assert (
        "Override values on a `percentage` flag are booleans that pin a user in (`true`) or out "
        "(`false`) of the rollout."
    ) in _GET_TEXT


def test_d1_an_outage_is_a_failed_or_over_budget_read() -> None:
    assert "The flag store is unreachable when its read fails or exceeds its read budget." in (
        _GET_TEXT
    )
    assert "returns an unreadable value" not in _GET_TEXT  # D1b revised: a bad row is no outage


def test_d1_an_unreadable_row_fails_closed_alone_and_stays_writable() -> None:
    assert (
        "A single unreadable stored row (malformed, or a kind mismatch) is not an outage. That "
        "flag alone resolves to its fail-closed value and is marked `unreadable: true`; it omits "
        "`default_value` (the stored value it cannot read) and `updated_by`, while every other "
        "flag resolves normally and `resolution` stays `stored`. The flag stays writable: its "
        "`updated_at` is still served, so a `PUT` with a valid value and that "
        "`expected_updated_at` repairs it."
    ) in _GET_TEXT
    assert "An unreadable stored row is not an outage: a write with a valid value repairs it." in (
        _PUT_TEXT
    )
    assert _SCHEMAS["FeatureFlag"]["properties"]["unreadable"]["type"] == "boolean"
    example = _list_example("flags")
    assert example["resolution"] == "stored"
    [bad] = [flag for flag in example["items"] if flag.get("unreadable")]
    assert (bad["key"], bad["value"], bad["unreadable"]) == ("killswitch.order_entry", True, True)
    assert "updated_at" in bad and not {"default_value", "updated_by"} & set(bad)


def test_d1_unreachable_store_resolves_every_flag_to_its_fail_closed_value() -> None:
    assert (
        "Every flag then resolves to its fail-closed value: the restrictive one for the "
        "safety-relevant flags (`maintenance.mode` and `killswitch.order_entry` engaged, so an "
        "unknown state refuses new orders through the shared order-entry gate; "
        "`trading.live_enabled` off) and the registry default for every other flag."
    ) in _GET_TEXT
    assert (
        "`killswitch.ingestion` is outside that restrictive set: it fails closed to its default, "
        "so an unreachable store never stops ingestion."
    ) in _GET_TEXT


def test_d1_the_list_answers_200_with_resolution_fail_closed() -> None:
    assert (
        "The answer is still `200`, with `resolution: fail_closed`, and every flag omits "
        "`updated_at` and `updated_by`, so the console can say these are fail-closed values, not "
        "the current ones."
    ) in _GET_TEXT
    schema = _LIST["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["properties"]["resolution"] == _ref("FeatureFlagResolution")
    assert _SCHEMAS["FeatureFlagResolution"]["enum"] == ["stored", "fail_closed"]


def test_d1_the_list_examples_show_both_resolutions() -> None:
    stored, failed = _list_example("flags"), _list_example("storeUnreachable")
    assert stored["resolution"] == "stored"
    assert all("updated_at" in flag for flag in stored["items"])
    assert failed["resolution"] == "fail_closed"
    assert not any({"updated_at", "updated_by"} & set(flag) for flag in failed["items"])
    values = {flag["key"]: flag["value"] for flag in failed["items"]}
    assert values == {"trading.live_enabled": False, "maintenance.mode": True}
    for flag in stored["items"] + failed["items"]:
        assert api.FeatureFlag.model_validate(flag).model_dump(exclude_unset=True, mode="json") == (
            flag
        )


def test_d1_a_write_without_the_store_is_503_store_unavailable() -> None:
    assert _PUT["responses"]["503"] == _ref("ServiceUnavailable", "responses")
    assert (
        "If the flag store is unreachable (as `GET /admin/feature-flags` defines it), the write is "
        "`503 store_unavailable` and nothing is written."
    ) in _PUT_TEXT


def test_d1_side_effects_follow_a_stored_true_never_a_store_failure() -> None:
    assert (
        "The algo cancels, the notice and the `maintenance.*` audit happen only on a stored value "
        "actually read as `true`, at the transition of the stored value, never on a transient "
        "store failure or an unreadable row: a fail-closed engagement only refuses new orders."
    ) in _PUT_TEXT


# --- D2: no per-caller value for a safety flag, at resolution and on write ----------------------


def test_d2_safety_flags_ignore_overrides_at_resolution() -> None:
    assert (
        "`trading.live_enabled` and the kill-switch-class flags (`maintenance.mode`, "
        "`killswitch.*`) resolve from the deployment value only: user and role overrides for them "
        "are ignored at resolution, not merely refused on write, so an override row that reached "
        "the store another way (a seed, a migration, a direct database change) changes nothing."
    ) in _GET_TEXT
    schema = _text((_DOCS / "21-database-schema.md").read_text(encoding="utf-8"))
    assert (
        "`trading.live_enabled` and every kill-switch-class flag (`is_killswitch`, "
        "`maintenance.mode` included) resolve from the deployment value only: user and role "
        "overrides for them are ignored at resolution, not merely refused on write"
    ) in schema


def test_d2_safety_flags_refuse_overrides_on_write() -> None:
    assert (
        "`trading.live_enabled` and the kill-switch-class flags take no overrides: any override "
        "on them is `422 validation_failed` (rule `overrides_not_allowed`), and resolution "
        "ignores any override row they hold (`GET /admin/feature-flags`)."
    ) in _PUT_TEXT


# --- D3: exactly one step-up class per write, by key and direction -------------------------------

_STEP_UP = re.compile(
    r"(releasing a kill-switch-class flag \(`true` to `false`\)|enabling `trading\.live_enabled`"
    r"|every other write) needs `(\w+)`"
)


def test_d3_one_step_up_class_per_write_by_key_and_direction() -> None:
    assert (
        "Every write needs exactly one fresh step-up elevation, chosen by key and direction: "
        "releasing a kill-switch-class flag (`true` to `false`) needs `killswitch`, enabling "
        "`trading.live_enabled` needs `live_enablement` (both no-grace, single use), and every "
        "other write needs `flags` (5-minute grace)."
    ) in _PUT_TEXT
    assert dict((m[1], m[2]) for m in _STEP_UP.finditer(_PUT_TEXT)) == {
        "releasing a kill-switch-class flag (`true` to `false`)": "killswitch",
        "enabling `trading.live_enabled`": "live_enablement",
        "every other write": "flags",
    }
    body = _SPEC["paths"]["/auth/step-up"]["post"]["requestBody"]["content"]["application/json"]
    assert {"killswitch", "live_enablement", "flags"} <= set(
        body["schema"]["properties"]["action_class"]["enum"]
    )


def test_d3_the_console_is_not_the_emergency_control() -> None:
    assert (
        "This console is not the emergency control: engaging a kill switch here needs only "
        "`flags`, and the code-free emergency engage stays `POST /trading/kill-switch`."
    ) in _PUT_TEXT
    for internal in ("ACTION_CLASSES", "DANGEROUS_ROUTES", "DANGEROUS_PATH_PATTERN"):
        assert internal not in _PUT_TEXT


# --- Kind rules: the GET sentence and the PUT bullet agree ---------------------------------------


def test_kind_rules_agree_between_the_list_and_the_write() -> None:
    assert (
        "`value` must match the flag's kind: a boolean on a `boolean` flag, an integer 0-100 on a "
        "`percentage` flag (its rollout), one of the flag's variants on a `variant` flag."
    ) in _PUT_TEXT
    assert (
        "An override value is a boolean on `boolean` and `percentage` flags (on a `percentage` "
        "flag it pins the user in or out of the rollout) and one of the flag's variants on a "
        "`variant` flag. Anything else is `422 validation_failed` (rule `kind_mismatch`)."
    ) in _PUT_TEXT
    # The list says the same about percentage overrides: booleans that pin a user in or out.
    assert "on a `percentage` flag are booleans that pin a user in" in _GET_TEXT


# --- D5: what maintenance mode refuses, and what stays available ---------------------------------


def test_d5_maintenance_refuses_new_orders_on_submit_routes_only() -> None:
    assert (
        "While it is on, the shared order-entry gate refuses new orders on submit routes only, "
        "before any OMS work, with `403 trading_disabled` and `reason: maintenance`. Cancel, "
        "reduce-only close, `closePosition` and `closeAllPositions` (flatten) and stop-loss "
        "tightening stay available, and so does the kill switch's own flatten; native exchange "
        "stop-losses are never touched."
    ) in _PUT_TEXT
    switch = _text(_SPEC["paths"]["/trading/kill-switch"]["post"]["description"])
    assert (
        "it refuses new orders on submit routes only, through the shared order-entry gate "
        "(`trading_disabled` with `reason: maintenance`), and cancels only running emulated algos. "
        "Cancel, reduce-only close, flatten and stop-loss tightening stay available under it, and "
        "so do this switch's own cancel and flatten."
    ) in switch


# --- D6: the push ---------------------------------------------------------------------------------


def _ws_doc() -> str:
    return (_DOCS / "23-ws-protocol.md").read_text(encoding="utf-8")


def test_d6_push_reaches_the_sessions_the_flag_visibility_admits() -> None:
    note = _ws_doc().split("**Feature-flag and maintenance pushes (E42-T03).**", 1)[1]
    note = _text(note.split("\n\n", 1)[0])
    assert (
        "`visibility` is a per-flag registry attribute: `all_roles`, or `owner_only` for a flag "
        "that only owner sessions receive. These frames bypass the 1 s `system` throttle (§8.1): "
        "flag writes are rare Owner-only actions, so they stay within the 2 s bound."
    ) in note
    assert "only the changed keys" in note and "owner-only key" in note
    assert "`maintenance.enabled`" in note and "`maintenance.disabled`" in note
    assert "Each definition also declares its `visibility`: `all_roles`, or `owner_only`" in (
        _GET_TEXT
    )


def test_d6_throttling_exempts_feature_flag_frames() -> None:
    rows = _ws_doc().split("### 8.1", 1)[1].split("### 8.2", 1)[0].splitlines()
    row = next(line for line in rows if line.startswith("| **Throttling** "))
    assert "All topics except `orders`, `executions`, and `system` frames of kind " in row
    assert "`feature_flags`" in row


def test_system_coalescing_keeps_every_flag_key_and_every_notice() -> None:
    rows = _ws_doc().split("### 8.2", 1)[1].split("### 8.3", 1)[0].splitlines()
    row = next(line for line in rows if line.startswith("| `system` "))
    assert "a key is never dropped" in row and "**never coalesced**" in row


# --- D7: write semantics -------------------------------------------------------------------------


def test_d7_overrides_omitted_keep_and_empty_clears() -> None:
    assert (
        "An omitted `overrides` keeps the flag's existing overrides; `overrides: []` clears them. "
        "An `overrides[].user_id` that names no user is `422 validation_failed` (rule "
        "`unknown_user`)."
    ) in _PUT_TEXT


def test_d7_the_lead_sentence_matches_the_bullets() -> None:
    assert (
        "Without `reason` the call fails `422 validation_failed` with rule `required`; without "
        "`evidence_url`, with rule `gate_evidence_required`."
    ) in _PUT_TEXT
    assert (
        "`evidence_url` must be an `https` URL (rule `https_required`); the server records it and "
        "never dereferences it."
    ) in _PUT_TEXT


def test_trading_disabled_names_maintenance_mode() -> None:
    entry = next(e for e in _SPEC["x-error-codes"] if e["code"] == "trading_disabled")
    assert "maintenance mode" in entry["title"]
