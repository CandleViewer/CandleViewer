"""Contract (E42-T03, contract slice): the flag list and write operations and the order-entry
gate text state the rules the flag service enforces. Every decision sentence is pinned verbatim in
one `(doc, sentence)` table, so a mutated rule fails here: resolution and the fail-closed answer
(D1), no overrides on safety flags (D2), one step-up class per write (D3, D3b), what maintenance
mode refuses (D5, D5b), the push and `visibility` (D6) and the write semantics (D7). The change
is additive (C-6.3): `SetFeatureFlagRequest` still requires only `value`."""

from __future__ import annotations

import re
from typing import Any

import pytest

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS

_SPEC = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_LIST = _SPEC["paths"]["/admin/feature-flags"]["get"]
_PUT = _SPEC["paths"]["/admin/feature-flags/{flagKey}"]["put"]
_REQUEST = _SCHEMAS["SetFeatureFlagRequest"]
_FLAG = _SCHEMAS["FeatureFlag"]["properties"]
_DOCS = OPENAPI_SPEC_PATH.parent  # docs/plan


def _ref(name: str, kind: str = "schemas") -> dict[str, str]:
    return {"$ref": f"#/components/{kind}/{name}"}


def _text(description: str) -> str:
    return " ".join(description.split())


def _doc(name: str) -> str:
    return (_DOCS / name).read_text(encoding="utf-8")


#: Where each pinned sentence lives, whitespace-normalised.
_TEXT = {
    "get": _text(_LIST["description"]),
    "put": _text(_PUT["description"]),
    "switch": _text(_SPEC["paths"]["/trading/kill-switch"]["post"]["description"]),
    "forbidden": _text(_SPEC["components"]["responses"]["Forbidden"]["description"]),
    "problem": _text(_SCHEMAS["TradingDisabledProblem"]["description"]),
    "flag": _text(f"{_FLAG['default_value']['description']} {_FLAG['overrides']['description']}"),
    "resolution": _text(_SCHEMAS["FeatureFlagResolution"]["description"]),
    "db": _text(_doc("21-database-schema.md")),
    "ws": _text(_doc("23-ws-protocol.md")),
    "gate": _text(_doc("24-internal-schemas.md")),
}
#: Every decision sentence, verbatim. Each one fails its row when a word of it is mutated.
_PINNED: dict[str, tuple[str, ...]] = {
    "get": (
        "Resolution (E42-T03) is server-side only, per caller: user override, then role override, "
        "then percentage rollout (`hash(user_id || flag_key)`), then the deployment default",
        "a flag may gate a UI surface or an incomplete feature, never authentication, RBAC "
        "enforcement, audit writing, the native-SL invariant, withdrawal permission or rate "
        "limiting (C-4.14), and the service refuses to start with a definition that declares one "
        "of them.",
        "Each definition must declare its `visibility`, which has no default: `all_roles`, or "
        "`owner_only` for a flag no manager or viewer session ever learns",
        "`trading.live_enabled` and the kill-switch-class flags (`maintenance.mode`, "
        "`killswitch.*`) resolve from the deployment value only: user and role overrides for them "
        "are ignored at resolution, not merely refused on write, so an override row that reached "
        "the store another way (a seed, a migration, a direct database change) changes nothing.",
        "Kill-switch-class flags are re-read at least every 5 s and never served from the 30 s "
        "cache. `trading.live_enabled` is not kill-switch-class, so the 30 s cache applies to it: "
        "the fast stop is the kill switch, at 5 s or less.",
        "Override values on a `percentage` flag are booleans that pin a user in (`true`) or out "
        "(`false`) of the rollout.",
        "The flag store is unreachable when its read fails or exceeds its read budget, the system "
        "setting `flags.read_budget_ms` (default 500 ms, well inside the 2 s push and 5 s re-read "
        "bounds; tunable).",
        "Every flag then resolves to its fail-closed value: the restrictive one for the "
        "safety-relevant flags (`maintenance.mode` and `killswitch.order_entry` engaged, so an "
        "unknown state refuses new orders through the shared order-entry gate; "
        "`trading.live_enabled` off) and the registry default for every other flag.",
        "`killswitch.ingestion` is outside that restrictive set: it fails closed to its default, "
        "so an unreachable store never stops ingestion.",
        "The answer is still `200`, with `resolution: fail_closed`, and every flag omits "
        "`default_value`, `overrides`, `updated_at` and `updated_by`, so the console can say these "
        "are fail-closed values, not the current ones. `resolution` is always sent.",
        "A single unreadable stored row (malformed, or a kind mismatch) is not an outage. That "
        "flag alone resolves to its fail-closed value and is marked `unreadable: true`; it omits "
        "`default_value` (the stored value it cannot read) and `updated_by`, while every other "
        "flag resolves normally and `resolution` stays `stored`. The flag stays writable: its "
        "`updated_at` is still served, so a `PUT` with a valid value and that "
        "`expected_updated_at` repairs it. An unreadable override row for a non-safety flag is "
        "ignored for that user, and a metric counts it.",
    ),
    "put": (
        "Without `reason` the call fails `422 validation_failed` with rule `required`; without "
        "`evidence_url`, with rule `gate_evidence_required`.",
        "Every write carries `reason` and `expected_updated_at` (the `updated_at` the caller last "
        "read). Without either the call fails `422 validation_failed` (rule `required`).",
        "`value` must match the flag's kind: a boolean on a `boolean` flag, an integer 0-100 on a "
        "`percentage` flag (its rollout), one of the flag's variants on a `variant` flag. An "
        "override value is a boolean on `boolean` and `percentage` flags (on a `percentage` flag "
        "it pins the user in or out of the rollout) and one of the flag's variants on a `variant` "
        "flag. Anything else is `422 validation_failed` (rule `kind_mismatch`). An unknown "
        "`flagKey` is `404 not_found`.",
        "An omitted `overrides` keeps the flag's existing overrides; `overrides: []` clears them. "
        "An `overrides[].user_id` that names no user is `422 validation_failed` (rule "
        "`unknown_user`).",
        "Every write needs exactly one fresh step-up elevation, chosen by key and by the flag's "
        "resolved value before the write, where a fail-closed engagement counts as engaged: "
        "releasing a kill-switch-class flag (engaged to `false`) needs `killswitch`, enabling "
        "`trading.live_enabled` needs `live_enablement` (both no-grace, single use), and every "
        "other write needs `flags` (5-minute grace). Repairing an `unreadable` kill-switch-class "
        "flag to `false` is therefore a release: it needs a fresh `killswitch` code, not `flags` "
        "with its 5-minute grace.",
        "Without that elevation the call is `403 step_up_required` (audited as "
        "`auth.step_up_required`).",
        "This console is not the emergency control: engaging a kill switch here needs only "
        "`flags`, and the code-free emergency engage stays `POST /trading/kill-switch`.",
        "`trading.live_enabled` and the kill-switch-class flags take no overrides: any override "
        "on them is `422 validation_failed` (rule `overrides_not_allowed`), and resolution "
        "ignores any override row they hold (`GET /admin/feature-flags`).",
        "A mismatch is `409 conflict` carrying the current flag in `current`; it is never "
        "last-write-wins. No `Idempotency-Key` is accepted: the precondition already makes a "
        "retry safe, so a `409` here is always `conflict` with `current`.",
        "`trading.live_enabled: true` without `evidence_url` is `422` (rule "
        "`gate_evidence_required`) and nothing is written. `evidence_url` must be an `https` URL "
        "(rule `https_required`); the server records it and never dereferences it.",
        "If the flag store is unreachable (as `GET /admin/feature-flags` defines it), the write is "
        "`503 store_unavailable` and nothing is written. An unreadable stored row is not an "
        "outage: a write with a valid value repairs it.",
        "audited as `flags.change` with the key, before, after, `reason` and `evidence_url`, "
        "including refused and conflicting ones. The one exception is `503 store_unavailable`: "
        "the audit lives in the same store, so that refusal cannot be audited and is logged with "
        "a metric instead (SR-125).",
        "A successful write pushes a `SystemUpdate` of kind `feature_flags`, carrying only the "
        "changed key, to every session the flag's `visibility` admits",
        "While it is on, the shared order-entry gate refuses every submission that opens or "
        "increases exposure, before any OMS work, with `403 trading_disabled` and `reason: "
        "maintenance` (`24-internal-schemas.md` 8.10 lists the submit paths and amends it "
        "covers). Cancels, `closePosition` and `closeAllPositions` (flatten), quantity-reducing "
        "and stop-tightening amends stay available, and so does the kill switch's own flatten; "
        "native exchange stop-losses are never touched.",
        "Turning it on cancels running emulated algos and sends every session a `notice`; the "
        "recorder keeps running unless `maintenance.keep_recorder` is `false`.",
        "The algo cancels, the notice and the `maintenance.*` audit happen only on a stored value "
        "actually read as `true`, at the transition of the stored value, never on a transient "
        "store failure or an unreadable row: a fail-closed engagement only refuses submissions. "
        "A boot that finds a stored `true` counts as a transition from unknown, so its side "
        "effects run.",
    ),
    "switch": (
        "narrower: through the shared order-entry gate it refuses every submission that opens or "
        "increases exposure (`trading_disabled` with `reason: maintenance`), and it cancels only "
        "running emulated algos. Cancels, flatten, quantity-reducing amends and stop-tightening "
        "amends stay available under it, and so do this switch's own cancel and flatten.",
    ),
    "ws": (
        "After a flag write commits, every authenticated connection that the flag's `visibility` "
        'admits receives a `system` frame of `kind: "feature_flags"` within 2 s. `visibility` is '
        "a mandatory per-flag registry attribute with no default: `all_roles`, or `owner_only` "
        "for a flag that only owner sessions receive",
        "These frames bypass the 1 s `system` throttle (§8.1): flag writes are rare Owner-only "
        "actions, so they stay within the 2 s bound. `feature_flags` carries **only the changed "
        "keys**,",
        "A key the role may not see is omitted, and a frame left with no key is not sent, so a "
        "manager or viewer never learns an owner-only key.",
        'Turning `maintenance.mode` on or off also sends `kind: "notice"` to every connection '
        "within 2 s, with `reason` `maintenance.enabled` (severity `warning`) or "
        "`maintenance.disabled` (severity `info`) and a role-neutral `message`.",
        "| All topics except `orders`, `executions` and `system` flag frames. |",
        "| `system` | `feature_flags`: per flag key, last-write-wins, a key is never dropped. "
        "`notice`, `kill_switch`, `shutdown_notice`: **never coalesced**. |",
    ),
    "db": (
        "`trading.live_enabled` and every kill-switch-class flag (`is_killswitch`, "
        "`maintenance.mode` included) resolve from the deployment value only: user and role "
        "overrides for them are ignored at resolution, not merely refused on write",
        "`default_value` is the deployment-wide stored value resolution falls back to: `PUT "
        "/admin/feature-flags/{flagKey}` writes it on a `boolean` or `variant` flag and writes "
        "`rollout_pct` on a `percentage` flag.",
        "is added to `feature_flags` by `0027_feature_flags`; slot 0027 is confirmed for it.",
        "| `flags.read_budget_ms` | `number` | milliseconds; default `500` |",
    ),
    "gate": (
        "One composed synchronous gate is consulted at the single OMS submission choke point, "
        "before any OMS work, for every submission that opens or increases exposure: REST order "
        "and trade-group submits, rule and paper legs, and emulated-algo child orders.",
        "A trade-group submit consults it once per leg's account. Risk-increasing amends "
        "(quantity up, stop loosened, trigger re-armed) are refused the same way. Cancels, "
        "`closePosition` and `closeAllPositions`, quantity-reducing amends and stop-tightening "
        "amends are never gated, so they keep working while order entry is paused (C-2.6).",
        "A `placeOrder` with `reduce_only` is a submission and is gated; closing goes through the "
        "close routes. The gate never inspects the order: `refusal(account_id)` sees only the "
        "account, and the caller classifies the operation. The gate runs after authentication, "
        "RBAC and account-scope resolution, so an account outside the caller's scope never "
        "reaches it and gets a `404`.",
        "The gate is a safety invariant: no flag gates it (C-4.14).",
        "| maintenance mode or the order-entry kill switch (the `killswitch.order_entry` flag, not "
        "the B18 kill switch) is on, or their state cannot be read (fail closed) |",
    ),
    "flag": (
        "A `PUT` writes it on a `boolean` or `variant` flag; on a `percentage` flag it writes "
        "`rollout_pct` instead. Omitted when the list's `resolution` is `fail_closed` or the flag "
        "is `unreadable`.",
        "Omitted when the list's `resolution` is `fail_closed` (E42-T03).",
    ),
    "resolution": (
        "a closed set; always sent. `stored`: from the flag store. `fail_closed`: the store was "
        "unreachable (its read failed or exceeded its read budget), so every flag shows its "
        "fail-closed value and omits `default_value`, `overrides`, `updated_at` and `updated_by`.",
    ),
    "forbidden": (
        "On an order submit or amend it may also be the order-entry gate's refusal: `code: "
        "trading_disabled` with a `reason` member (`TradingDisabledProblem`, #837 Q5). `reason` "
        "appears on gate refusals only: the B18 kill switch (FREEZE) and the live-not-enabled "
        "refusal are separate synchronous checks ahead of the gate, and they return "
        "`trading_disabled` without a `reason`.",
    ),
    "problem": (
        "The gate runs after authentication, RBAC and account-scope resolution, so an account "
        "outside the caller's scope never reaches it and gets a `404`. Cancels, flatten and "
        "quantity-reducing or stop-tightening amends never pass through the gate.",
    ),
}
#: D5b, refined by the gate's Fable security delta (C-2.6): stated wherever D5b is.
_PROTECTIVE = (
    "Attaching a missing native SL, tightening a stop, or re-arming a protective trigger is never "
    'gated; "trigger re-armed" means an exposure-increasing (entry) trigger. An amend with any '
    "risk-increasing component is gated."
)
_ROWS = [(doc, sentence) for doc, sentences in _PINNED.items() for sentence in sentences]
_ROWS += [(doc, _PROTECTIVE) for doc in ("put", "switch", "gate", "problem")]


@pytest.mark.parametrize(("doc", "sentence"), _ROWS, ids=[doc for doc, _ in _ROWS])
def test_every_decision_sentence_is_pinned(doc: str, sentence: str) -> None:
    assert sentence in _TEXT[doc]


def test_put_documents_every_refusal_and_takes_no_idempotency_key() -> None:
    assert set(_PUT["responses"]) == {"200", "401", "403", "404", "409", "422", "503"}
    assert set(_LIST["responses"]) == {"200", "401", "403"}
    assert _PUT["responses"]["503"] == _ref("ServiceUnavailable", "responses")
    assert _PUT["x-idempotency"] == "ignored"
    codes = {entry["code"] for entry in _SPEC["x-error-codes"]}
    assert {"validation_failed", "step_up_required", "conflict", "not_found"} <= codes
    assert "store_unavailable" in codes
    assert "flags.change" in AUDIT_ACTIONS  # `maintenance.*` are the registry slice's


def test_conflict_answer_carries_the_current_flag() -> None:
    content = _PUT["responses"]["409"]["content"]["application/problem+json"]
    assert content["schema"] == _ref("FeatureFlagConflict")
    problem, extra = _SCHEMAS["FeatureFlagConflict"]["allOf"]
    assert (problem, extra["required"]) == (_ref("Problem"), ["current"])
    assert extra["properties"]["current"] == _ref("FeatureFlag")
    assert set(api.FeatureFlagConflict.model_fields) == set(api.Problem.model_fields) | {"current"}
    example = content["examples"]["staleRead"]["value"]
    model = api.FeatureFlagConflict.model_validate(example)
    assert model.model_dump(mode="json", exclude_unset=True) == example
    assert (model.code, model.status) == ("conflict", 409)


def test_request_change_is_additive_only() -> None:
    props = _REQUEST["properties"]
    assert (_REQUEST["required"], _REQUEST["additionalProperties"]) == (["value"], False)
    assert (props["reason"]["type"], props["reason"]["maxLength"]) == ("string", 280)
    assert (props["evidence_url"]["format"], props["evidence_url"]["maxLength"]) == ("uri", 2048)
    stamp = props["expected_updated_at"]
    assert (stamp["type"], stamp["format"]) == ("string", "date-time")
    assert set(props) == {"value", "overrides", "reason", "evidence_url", "expected_updated_at"}
    assert set(api.SetFeatureFlagRequest.model_fields) == set(props)
    body = _PUT["requestBody"]["content"]["application/json"]["examples"]["enableLive"]["value"]
    model = api.SetFeatureFlagRequest.model_validate(body)
    assert model.model_dump(mode="json", exclude_unset=True) == body


def _catalogue() -> dict[str, list[str]]:
    """`21-database-schema.md` 10.7: key -> [kind, default, purpose, visibility]."""
    table = _doc("21-database-schema.md").split("### 10.7 Feature flags", 1)[1].split("###", 1)[0]
    return {
        row.split("|")[1].strip().strip("`"): [cell.strip() for cell in row.split("|")[2:6]]
        for row in table.splitlines()
        if row.startswith("| `")
    }


def test_catalogue_rows_carry_defaults_and_the_decided_visibility() -> None:
    rows = _catalogue()
    assert rows["maintenance.mode"][:2] == ["boolean", "`false`"]
    assert "is_killswitch=true" in rows["maintenance.mode"][2]
    assert rows["maintenance.keep_recorder"][:2] == ["boolean", "`true`"]
    visibility = {key: cells[3] for key, cells in rows.items()}
    assert set(visibility.values()) == {"`all_roles`", "`owner_only`"}
    assert {key for key, value in visibility.items() if value == "`owner_only`"} == {
        "killswitch.ingestion",
        "storage.cold_tier",
        "recorder.auto_record",
        "maintenance.keep_recorder",
    }


def _list_example(name: str) -> dict[str, Any]:
    examples = _LIST["responses"]["200"]["content"]["application/json"]["examples"]
    value: dict[str, Any] = examples[name]["value"]
    return value


def test_d1_the_list_examples_show_both_resolutions() -> None:
    schema = _LIST["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["properties"]["resolution"] == _ref("FeatureFlagResolution")
    assert _SCHEMAS["FeatureFlagResolution"]["enum"] == ["stored", "fail_closed"]
    assert _FLAG["unreadable"]["type"] == "boolean" and "unreadable" in api.FeatureFlag.model_fields
    assert "returns an unreadable value" not in _TEXT["get"]  # D1b: a bad row is no outage
    stored, failed = _list_example("flags"), _list_example("storeUnreachable")
    assert (stored["resolution"], failed["resolution"]) == ("stored", "fail_closed")
    assert all("updated_at" in flag for flag in stored["items"])
    [bad] = [flag for flag in stored["items"] if flag.get("unreadable")]
    assert (bad["key"], bad["value"], bad["unreadable"]) == ("killswitch.order_entry", True, True)
    assert not {"default_value", "updated_by"} & set(bad)
    omitted = {"default_value", "overrides", "updated_at", "updated_by"}
    assert not any(omitted & set(flag) for flag in failed["items"])
    values = {flag["key"]: flag["value"] for flag in failed["items"]}
    assert values == {"trading.live_enabled": False, "maintenance.mode": True}
    assert {flag["key"] for flag in stored["items"] + failed["items"]} <= set(_catalogue())
    for flag in stored["items"] + failed["items"]:
        model = api.FeatureFlag.model_validate(flag)
        assert model.model_dump(exclude_unset=True, mode="json") == flag


_STEP_UP = re.compile(
    r"(releasing a kill-switch-class flag \(engaged to `false`\)|enabling `trading\.live_enabled`"
    r"|every other write) needs `(\w+)`"
)


def test_d3_one_step_up_class_per_write_and_no_internal_names() -> None:
    assert dict((m[1], m[2]) for m in _STEP_UP.finditer(_TEXT["put"])) == {
        "releasing a kill-switch-class flag (engaged to `false`)": "killswitch",
        "enabling `trading.live_enabled`": "live_enablement",
        "every other write": "flags",
    }
    body = _SPEC["paths"]["/auth/step-up"]["post"]["requestBody"]["content"]["application/json"]
    classes = set(body["schema"]["properties"]["action_class"]["enum"])
    assert {"killswitch", "live_enablement", "flags"} <= classes
    for internal in ("ACTION_CLASSES", "DANGEROUS_ROUTES", "DANGEROUS_PATH_PATTERN"):
        assert internal not in _TEXT["put"]
