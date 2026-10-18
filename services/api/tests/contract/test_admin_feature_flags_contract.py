"""Contract (E42-T03): the flag operations and the order-entry gate text state the rules the flag
service enforces, each decision pinned verbatim (one paragraph or bullet per row of one `(doc,
sentence)` table): D1 to D7a, D3b and D5b. Additive (C-6.3): the request still requires `value`."""

from __future__ import annotations

import re
from typing import Any

import pytest

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.api.feature_flags import _REFUSED
from candleviewer.audit.actions import AUDIT_ACTIONS

_SPEC = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_LIST = _SPEC["paths"]["/admin/feature-flags"]["get"]
_PUT = _SPEC["paths"]["/admin/feature-flags/{flagKey}"]["put"]
_REQUEST = _SCHEMAS["SetFeatureFlagRequest"]
_FLAG = _SCHEMAS["FeatureFlag"]["properties"]
_PLAN = OPENAPI_SPEC_PATH.parent  # docs/plan
_DB = (_PLAN / "21-database-schema.md").read_text(encoding="utf-8")


def _ref(name: str, kind: str = "schemas") -> dict[str, str]:
    return {"$ref": f"#/components/{kind}/{name}"}


def _text(description: str) -> str:
    return " ".join(description.split())


#: Where each pinned row lives, whitespace-normalised.
_TEXT = {
    "get": _text(_LIST["description"]),
    "put": _text(_PUT["description"]),
    "switch": _text(_SPEC["paths"]["/trading/kill-switch"]["post"]["description"]),
    "forbidden": _text(_SPEC["components"]["responses"]["Forbidden"]["description"]),
    "problem": _text(_SCHEMAS["TradingDisabledProblem"]["description"]),
    "flag": _text(f"{_FLAG['default_value']['description']} {_FLAG['overrides']['description']}"),
    "resolution": _text(_SCHEMAS["FeatureFlagResolution"]["description"]),
    "db": _text(_DB),
    "ws": _text((_PLAN / "23-ws-protocol.md").read_text(encoding="utf-8")),
    "gate": _text((_PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")),
}
#: D5b, refined by the gate's Fable security delta (C-2.6): stated wherever D5b is.
_PROTECTIVE = (
    "Attaching a missing native SL, tightening a stop, or re-arming a protective trigger is never "
    'gated; "trigger re-armed" means an exposure-increasing (entry) trigger. An amend with any '
    "risk-increasing component is gated."
)
#: Every decision, verbatim: one paragraph or bullet per row, so a mutated word fails its row.
_PINNED: dict[str, tuple[str, ...]] = {
    "get": (
        "Resolution (E42-T03) is server-side only, per caller: user override, then role override, "
        "then percentage rollout (`hash(user_id || flag_key)`), then the deployment default "
        "(`21-database-schema.md` 3.9). Flag definitions are code (a reviewed registry), never "
        "configuration: a flag may gate a UI surface or an incomplete feature, never "
        "authentication, RBAC enforcement, audit writing, the native-SL invariant, withdrawal "
        "permission or rate limiting (C-4.14), and the service refuses to start with a definition "
        "that declares one of them. Each definition must declare its `visibility`, which has no "
        "default: `all_roles`, or `owner_only` for a flag no manager or viewer session ever "
        "learns (`21-database-schema.md` 10.7 gives each flag's; `23-ws-protocol.md` 15.9). "
        "`trading.live_enabled` and the kill-switch-class flags (`maintenance.mode`, "
        "`killswitch.*`) resolve from the deployment value only: user and role overrides for them "
        "are ignored at resolution, not merely refused on write, so an override row that reached "
        "the store another way (a seed, a migration, a direct database change) changes nothing. "
        "Kill-switch-class flags are re-read at least every 5 s and never served from the 30 s "
        "cache. `trading.live_enabled` is not kill-switch-class, so the 30 s cache applies to it: "
        "the fast stop is the kill switch, at 5 s or less. Override values on a `percentage` flag "
        "are booleans that pin a user in (`true`) or out (`false`) of the rollout.",
        "The flag store is unreachable when its read fails or exceeds its read budget, the system "
        "setting `flags.read_budget_ms` (default 500 ms, tunable from 50 to 2000 ms, so never "
        "more than the 2 s push bound; an out-of-range configured value refuses startup). Every "
        "flag then resolves to its fail-closed value: the restrictive one for the safety-relevant "
        "flags (`maintenance.mode` and `killswitch.order_entry` engaged, so an unknown state "
        "refuses new orders through the shared order-entry gate; `trading.live_enabled` off) and "
        "the registry default for every other flag. `killswitch.ingestion` is outside that "
        "restrictive set: it fails closed to its default, so an unreachable store never stops "
        "ingestion. The answer is still `200`, with `resolution: fail_closed`, and every flag "
        "omits `default_value`, `overrides`, `updated_at` and `updated_by`, so the console can "
        "say these are fail-closed values, not the current ones. `resolution` is always sent.",
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
        "`reason` and every other string value of the request (`evidence_url`, "
        "`expected_updated_at`, an override's `user_id`, and `value` and an override's `value` on "
        "a `variant` flag), and every object member name in it, refuse control, zero-width and "
        "bidirectional formatting characters, line and paragraph separators, tag characters and "
        "lone surrogates, so that a recorded text cannot render as other text: U+0000 to U+001F "
        r"(`\t`, `\n` and `\r` included, so a multi-line `reason` is refused), U+007F to U+009F "
        "(DEL and the C1 controls), U+061C (the Arabic letter mark), U+200B to U+200F (ZWNJ and "
        "ZWJ included, so an emoji ZWJ sequence is refused), U+2028 and U+2029, U+202A to "
        "U+202E, U+2066 to U+2069, U+D800 to U+DFFF, U+FEFF (the byte order mark) and U+E0000 "
        "to U+E007F (the Tags block). The call fails `422 validation_failed` (rule "
        "`invalid_character`) and nothing is written, also for a member name the request does "
        "not define (never `extra_forbidden`).",
        "Decision order: authentication; RBAC and scope, before any validation that needs a "
        "lookup, so a caller without `flags:write` learns nothing from a `422`; request "
        "validation; then, under the row lock, the step-up gate, the precondition and the write.",
        "`flags:write` is a dangerous permission. Every write needs exactly one fresh step-up "
        "elevation, chosen by key and by the stored value read under the row lock that "
        "`expected_updated_at` is checked against, never the cached value. An unreadable row "
        "counts as its fail-closed value (engaged for a kill-switch-class flag, off for "
        "`trading.live_enabled`): releasing a kill-switch-class flag (`true` to `false`) needs "
        "`killswitch`, writing `true` to `trading.live_enabled` needs `live_enablement` whatever "
        "is stored (both no-grace, single use), and every other write needs `flags` (5-minute "
        "grace). So repairing an `unreadable` kill-switch-class flag to `false` is a release "
        "(`killswitch`). Without that elevation the call is `403 step_up_required`. This console "
        "is not the emergency control: engaging a kill switch here needs only `flags`, and the "
        "code-free emergency engage stays `POST /trading/kill-switch`.",
        "`trading.live_enabled` and the kill-switch-class flags take no overrides: any override "
        "on them is `422 validation_failed` (rule `overrides_not_allowed`), and resolution "
        "ignores any override row they hold (`GET /admin/feature-flags`).",
        "The write locks the flag row and compares `expected_updated_at` with the stored "
        "`updated_at`. A mismatch is `409 conflict` carrying the current flag in `current`; it is "
        "never last-write-wins. No `Idempotency-Key` is accepted: the precondition already makes "
        "a retry safe, so a `409` here is always `conflict` with `current`.",
        "`trading.live_enabled: true` without `evidence_url` is `422` (rule "
        "`gate_evidence_required`) and nothing is written. `evidence_url` must be an `https` URL "
        "(rule `https_required`) of at most 2048 characters (rule `string_too_long`). The audit "
        "records it, so the write rejects userinfo and any query or fragment parameter named on a "
        "token deny-list (rule `credential_in_url`); a path token is an accepted residual. The "
        "service validates it (the generated model checks only the URI format), never "
        "dereferences it and only enforces the precondition; E44-T04 owns the evidence binding.",
        "If the flag store is unreachable (as `GET /admin/feature-flags` defines it), the write "
        "is `503 store_unavailable` and nothing is written. An unreadable stored row is not an "
        "outage: a write with a valid value repairs it.",
        "Every attempt past authentication and RBAC is audited as `flags.change` with the key, "
        "before, after, `reason` and `evidence_url`, including refused and conflicting ones and "
        "every `422` (such as `gate_evidence_required`, `kind_mismatch`, `unknown_user` and "
        "`overrides_not_allowed`); a `step_up_required` challenge writes `auth.step_up_required` "
        "and no `flags.change`, and one that refuses a no-grace grant bound to another request "
        "also writes `auth.step_up_mismatch`, ahead of its `403`. The `flags.change` record is "
        "durable before the flag write commits, or the write is refused (write-ahead, C-2.9). A "
        "`503 store_unavailable` (no row can be read) is logged instead, with only the key and "
        "correlation id, plus a metric (SR-125). An unreadable row's `before` is `unreadable`, "
        "never its raw value. Toggling `maintenance.mode` is also audited as "
        "`maintenance.enabled` or `maintenance.disabled`.",
        "A successful write pushes a `SystemUpdate` of kind `feature_flags`, carrying only the "
        "changed key, to every session the flag's `visibility` admits (`23-ws-protocol.md` 15.9).",
        "`maintenance.mode` is a kill-switch-class flag. While it is on, the shared order-entry "
        "gate refuses every submission that opens or increases exposure, before any OMS work, "
        "with `403 trading_disabled` and `reason: maintenance` (`24-internal-schemas.md` 8.10 "
        "lists the submit paths and amends it covers). Cancels, `closePosition` and "
        "`closeAllPositions` (flatten), quantity-reducing and stop-tightening amends stay "
        "available, and so does the kill switch's own flatten; native exchange stop-losses are "
        "never touched. "
        + _PROTECTIVE
        + " Turning it on cancels only running emulated algos, so resting entry orders can still "
        "fill, and sends every session a `notice`; the recorder keeps running unless "
        "`maintenance.keep_recorder` is `false`. The algo cancels, the notice and the "
        "`maintenance.*` audit happen only on a stored value actually read as `true`, at the "
        "transition of the stored value, never on a transient store failure or an unreadable row: "
        "a fail-closed engagement only refuses submissions. A boot that finds a stored `true` "
        "counts as a transition from unknown, so its side effects run.",
    ),
    "switch": (
        "Maintenance mode (`maintenance.mode`, set with `PUT /admin/feature-flags/{flagKey}`) is "
        "narrower: through the shared order-entry gate it refuses every submission that opens or "
        "increases exposure (`trading_disabled` with `reason: maintenance`), and it cancels only "
        "running emulated algos, so resting entry orders can still fill. Cancels, flatten, "
        "quantity-reducing amends and stop-tightening amends stay available under it, and so do "
        "this switch's own cancel and flatten. " + _PROTECTIVE,
    ),
    "forbidden": (
        "On an order submit or amend it may also be the order-entry gate's refusal: `code: "
        "trading_disabled` with a `reason` member (`TradingDisabledProblem`, #837 Q5). `reason` "
        "appears on gate refusals only: the B18 kill switch (FREEZE) and the live-not-enabled "
        "refusal are separate synchronous checks ahead of the gate, and they return "
        "`trading_disabled` without a `reason`. Like the gate, they run after authentication, "
        "RBAC and account-scope resolution, and the C-2.6 carve-out binds every synchronous "
        "refusal, not just the gate: attaching a missing native SL, tightening a stop or "
        "re-arming a protective trigger is never refused.",
    ),
    "problem": (
        "The `403 trading_disabled` problem the order-entry gate returns when it refuses a "
        "submission or amend that opens or increases exposure, before any OMS work (C-2.21): the "
        "problem body plus the gate's `reason`. `detail` is human text and never carries an id or "
        "a secret. The gate runs after authentication, RBAC and account-scope resolution, so an "
        "account outside the caller's scope never reaches it and gets a `404`. Cancels, flatten "
        "and quantity-reducing or stop-tightening amends never pass through the gate. "
        + _PROTECTIVE,
    ),
    "flag": (
        "A `PUT` writes it on a `boolean` or `variant` flag; on a `percentage` flag it writes "
        "`rollout_pct` instead. Omitted when the list's `resolution` is `fail_closed` or the flag "
        "is `unreadable`.",
        "Omitted when the list's `resolution` is `fail_closed` (E42-T03).",
    ),
    "resolution": (
        "How `GET /admin/feature-flags` resolved its list (E42-T03), a closed set; always sent. "
        "`stored`: from the flag store. `fail_closed`: the store was unreachable (its read failed "
        "or exceeded its read budget), so every flag shows its fail-closed value and omits "
        "`default_value`, `overrides`, `updated_at` and `updated_by`. A single unreadable row is "
        "not an outage: the list stays `stored` and that flag is marked `unreadable`.",
    ),
    "db": (
        "`trading.live_enabled` and every kill-switch-class flag (`is_killswitch`, "
        "`maintenance.mode` included) resolve from the deployment value only: user and role "
        "overrides for them are ignored at resolution, not merely refused on write, so an "
        "override row that reaches this table another way (a seed, a migration, a direct change) "
        "changes nothing (E42-T03). Every other flag is served from a 30 s cache (TTL), "
        "`trading.live_enabled` included.",
        "**Stored value and writer (E42-T03).** `default_value` is the deployment-wide stored "
        "value resolution falls back to: `PUT /admin/feature-flags/{flagKey}` writes it on a "
        "`boolean` or `variant` flag and writes `rollout_pct` on a `percentage` flag. "
        "`FeatureFlag.value` is the per-caller resolved value, so there is no separate "
        "current-value column. `updated_by` (`FeatureFlag.updated_by`) shipped with "
        "`0027_feature_flags` (the note above).",
        "| `flags.read_budget_ms` | `number` | ms, 50 to 2000; default `500` | The flag store's "
        "read budget (E42-T03): a read that fails or takes longer is a store outage, so `GET "
        "/admin/feature-flags` answers `resolution: fail_closed`. A configured value out of range "
        "refuses startup; there is no REST write. |",
    ),
    "ws": (
        "**Feature-flag and maintenance pushes (E42-T03).** After a flag write commits, every "
        "authenticated connection that the flag's `visibility` admits receives a `system` frame "
        'of `kind: "feature_flags"` within 2 s. `visibility` is a mandatory per-flag registry '
        "attribute with no default: `all_roles`, or `owner_only` for a flag that only owner "
        "sessions receive (`21-database-schema.md` §10.7 gives each flag's). These frames bypass "
        "the 1 s `system` throttle (§8.1): flag writes are rare Owner-only actions, so they stay "
        "within the 2 s bound. `feature_flags` carries **only the changed keys**, each resolved "
        "for that connection's user exactly as `GET /admin/feature-flags` resolves it, so a "
        "client merges the frame into the set it holds rather than replacing the set. A key the "
        "role may not see is omitted, and a frame left with no key is not sent, so a manager or "
        "viewer never learns an owner-only key. The topic snapshot carries the full set the role "
        'may see. Turning `maintenance.mode` on or off also sends `kind: "notice"` to every '
        "connection within 2 s, with `reason` `maintenance.enabled` (severity `warning`) or "
        "`maintenance.disabled` (severity `info`) and a role-neutral `message`. This uses the "
        "existing schema; no schema change.",
        "| All topics except `orders`, `executions` and `system` flag frames. |",
        "| `system` | `feature_flags`: per flag key, last-write-wins, a key is never dropped. "
        "`notice`, `kill_switch`, `shutdown_notice`: **never coalesced**. | A flag delta carries "
        "only changed keys; notices are events. |",
        # 15.9 per role (SR-188): the snapshot's `health` frame and a flag frame are cut alike.
        "`degraded_topics`, `kill_switch` and `feature_flags` (each as below) |",
        "| `feature_flags` | `feature_flags` with only the keys whose registry `visibility` admits "
        "the role, never one that no flag definition names; left out when none remains, and then a "
        "frame of this kind is not sent |",
        "the `owner_only` flag keys and any key that no flag definition names reach the Owner "
        "only.",
    ),
    "gate": (
        "One composed synchronous gate is consulted at the single OMS submission choke point, "
        "before any OMS work, for every submission that opens or increases exposure: REST order "
        "and trade-group submits, rule and paper legs, and emulated-algo child orders. A "
        "trade-group submit consults it once per leg's account, as each leg is sent: a refused "
        "leg is a failed leg, so the group's `leg_failure_policy` applies (§9.5). An "
        "`all_or_none` unwind, like any reduce-only close, goes as the reduce-only MARKET close "
        "of §9.5.1 and B3 `reduce_only_close`, never as a gated `placeOrder`. Risk-increasing "
        "amends (quantity up, stop loosened, trigger re-armed) are refused the same way. Cancels, "
        "`closePosition` and `closeAllPositions`, quantity-reducing amends and stop-tightening "
        "amends are never gated, so they keep working while order entry is paused (C-2.6). "
        + _PROTECTIVE
        + " A take-profit change is never a risk-increasing component. The SL component of a "
        "`trading-stop` write is never refused when it adds, keeps or tightens protection; "
        "loosening or clearing it is classified like a stop-loosening amend. The operations that "
        "attach or re-arm a protective stop are `trading-stop` and the SL fields of an amend; a "
        "protective stop is never sent as a gated `placeOrder`. A `placeOrder` with `reduce_only` "
        "is a submission and is gated; closing goes through the close routes. The gate never "
        "inspects the order: `refusal(account_id)` sees only the account, and the caller "
        "classifies the operation. The gate runs after authentication, RBAC and account-scope "
        "resolution, so an account outside the caller's scope never reaches it and gets a `404`. "
        "The B18 kill switch (FREEZE) and the live-not-enabled refusal are separate synchronous "
        "checks ahead of the gate; they too run after authentication, RBAC and account-scope "
        "resolution, and the C-2.6 carve-out binds every synchronous refusal, not just the gate. "
        "The gate's checks run in a fixed order, the global maintenance gate first, then the "
        "account checks; the first refusal wins. A check is synchronous and O(1), does no I/O and "
        "never queries an interpreter; it reads a plain bool or enum that its monitor publishes "
        "on transition (C-2.20). The gate is a safety invariant: no flag gates it (C-4.14).",
        "| maintenance mode or the order-entry kill switch (the `killswitch.order_entry` flag, "
        "not the B18 kill switch) is on, or their state cannot be read (fail closed) |",
    ),
}

_ROWS = [(doc, row) for doc, rows in _PINNED.items() for row in rows]


@pytest.mark.parametrize(("doc", "sentence"), _ROWS, ids=[doc for doc, _ in _ROWS])
def test_every_decision_sentence_is_pinned(doc: str, sentence: str) -> None:
    assert sentence in _TEXT[doc]


def _named_code_points(text: str) -> set[str]:
    """The characters the `U+XXXX` and `U+XXXX to U+XXXX` items of `text` name: four to six hex
    digits, so that a five-digit range such as the Tags block is read whole."""
    return {
        chr(code)
        for first, last in re.findall(r"U\+([0-9A-F]{4,6})(?: to U\+([0-9A-F]{4,6}))?", text)
        for code in range(int(first, 16), int(last or first, 16) + 1)
    }


def test_the_code_point_reader_reads_five_digit_items_whole() -> None:
    tags = {chr(code) for code in range(0xE0000, 0xE0080)}
    assert _named_code_points("U+E0000 to U+E007F") == tags
    assert _named_code_points("U+FEFF, U+2028 and U+E0041") == {
        chr(0xFEFF),
        chr(0x2028),
        chr(0xE0041),
    }


def test_put_names_exactly_the_code_points_the_route_refuses() -> None:
    """Widening or narrowing `feature_flags._REFUSED` fails here until the contract's
    `invalid_character` row says so too (C-6.1)."""
    [row] = [r for r in _PINNED["put"] if "`invalid_character`" in r]
    every_code_point = "".join(map(chr, range(0x110000)))
    assert _named_code_points(row) == set(_REFUSED.findall(every_code_point))


def test_put_answers_step_up_classes_conflict_and_additive_request() -> None:
    assert set(_PUT["responses"]) == {"200", "401", "403", "404", "409", "422", "503"}
    assert set(_LIST["responses"]) == {"200", "401", "403", "503"}  # 503: #2295 guard
    assert _PUT["responses"]["503"] == _ref("ServiceUnavailable", "responses")
    assert _PUT["x-idempotency"] == "ignored"
    codes = {"validation_failed", "step_up_required", "conflict", "not_found", "store_unavailable"}
    assert codes <= {entry["code"] for entry in _SPEC["x-error-codes"]}
    assert "flags.change" in AUDIT_ACTIONS  # `maintenance.*` are the registry slice's
    step_up = re.compile(
        r"(releasing a kill-switch-class flag \(`true` to `false`\)"
        r"|writing `true` to `trading\.live_enabled`|every other write) needs `(\w+)`"
    )
    assert dict((m[1], m[2]) for m in step_up.finditer(_TEXT["put"])) == {
        "releasing a kill-switch-class flag (`true` to `false`)": "killswitch",
        "writing `true` to `trading.live_enabled`": "live_enablement",
        "every other write": "flags",
    }
    body = _SPEC["paths"]["/auth/step-up"]["post"]["requestBody"]["content"]["application/json"]
    classes = set(body["schema"]["properties"]["action_class"]["enum"])
    assert {"killswitch", "live_enablement", "flags"} <= classes
    for internal in ("ACTION_CLASSES", "DANGEROUS_ROUTES", "DANGEROUS_PATH_PATTERN"):
        assert internal not in _TEXT["put"]
    content = _PUT["responses"]["409"]["content"]["application/problem+json"]
    problem, extra = _SCHEMAS["FeatureFlagConflict"]["allOf"]
    assert (content["schema"], problem) == (_ref("FeatureFlagConflict"), _ref("Problem"))
    assert (extra["required"], extra["properties"]["current"]) == (["current"], _ref("FeatureFlag"))
    assert set(api.FeatureFlagConflict.model_fields) == set(api.Problem.model_fields) | {"current"}
    props = _REQUEST["properties"]
    assert (_REQUEST["required"], _REQUEST["additionalProperties"]) == (["value"], False)
    assert (props["reason"]["type"], props["reason"]["maxLength"]) == ("string", 280)
    assert (props["evidence_url"]["format"], props["evidence_url"]["maxLength"]) == ("uri", 2048)
    stamp = props["expected_updated_at"]
    assert (stamp["type"], stamp["format"]) == ("string", "date-time")
    assert set(props) == {"value", "overrides", "reason", "evidence_url", "expected_updated_at"}
    assert set(api.SetFeatureFlagRequest.model_fields) == set(props)
    request = _PUT["requestBody"]["content"]["application/json"]["examples"]["enableLive"]["value"]
    stale = content["examples"]["staleRead"]["value"]
    for model, example in ((api.FeatureFlagConflict, stale), (api.SetFeatureFlagRequest, request)):
        assert model.model_validate(example).model_dump(mode="json", exclude_unset=True) == example
    assert (stale["code"], stale["status"]) == ("conflict", 409)
    assert request["evidence_url"].startswith("https://")


#: `21-database-schema.md` 10.7: key -> [kind, default, purpose, visibility].
_CATALOGUE = {
    row.split("|")[1].strip().strip("`"): [cell.strip() for cell in row.split("|")[2:6]]
    for row in _DB.split("### 10.7 Feature flags", 1)[1].split("###", 1)[0].splitlines()
    if row.startswith("| `")
}


def test_catalogue_rows_carry_defaults_and_the_decided_visibility() -> None:
    assert _CATALOGUE["maintenance.mode"][:2] == ["boolean", "`false`"]
    assert "is_killswitch=true" in _CATALOGUE["maintenance.mode"][2]
    assert _CATALOGUE["maintenance.keep_recorder"][:2] == ["boolean", "`true`"]
    visibility = {key: cells[3] for key, cells in _CATALOGUE.items()}
    assert set(visibility.values()) == {"`all_roles`", "`owner_only`"}
    owner_only = " ".join(sorted(k for k, value in visibility.items() if value == "`owner_only`"))
    assert owner_only == (
        "killswitch.ingestion maintenance.keep_recorder recorder.auto_record storage.cold_tier"
    )


def test_d1_the_list_examples_show_both_resolutions() -> None:
    content = _LIST["responses"]["200"]["content"]["application/json"]
    schema, examples = content["schema"], content["examples"]
    assert schema["properties"]["resolution"] == _ref("FeatureFlagResolution")
    assert schema["required"] == ["resolution"]
    assert _SCHEMAS["FeatureFlagResolution"]["enum"] == ["stored", "fail_closed"]
    assert _FLAG["unreadable"]["type"] == "boolean" and "unreadable" in api.FeatureFlag.model_fields
    assert "returns an unreadable value" not in _TEXT["get"]  # D1b: a bad row is no outage
    stored, failed = examples["flags"]["value"], examples["storeUnreachable"]["value"]
    assert (stored["resolution"], failed["resolution"]) == ("stored", "fail_closed")
    assert all("updated_at" in flag for flag in stored["items"])
    [bad] = [flag for flag in stored["items"] if flag.get("unreadable")]
    assert (bad["key"], bad["value"], bad["unreadable"]) == ("killswitch.order_entry", True, True)
    assert not {"default_value", "updated_by"} & set(bad)
    omitted = {"default_value", "overrides", "updated_at", "updated_by"}
    assert not any(omitted & set(flag) for flag in failed["items"])
    values = {flag["key"]: flag["value"] for flag in failed["items"]}
    assert values == {"trading.live_enabled": False, "maintenance.mode": True}
    assert {flag["key"] for flag in stored["items"] + failed["items"]} <= set(_CATALOGUE)
    for flag in stored["items"] + failed["items"]:
        model = api.FeatureFlag.model_validate(flag)
        assert model.model_dump(exclude_unset=True, mode="json") == flag
