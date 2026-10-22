"""Contract (#906, E28-T02 slice 0c): the profile operations declare their answers and errors."""

from __future__ import annotations

import re

import pytest

from candleviewer.accounts.errors import AccountVersionConflictError
from candleviewer.api._generated import openapi_models as api
from candleviewer.audit.actions import PROFILE_SAVE_REFUSED_REASONS
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.contract._admin_support import ROOT, SPEC, validate_example
from tests.contract._admin_support import text as _text  # not `text`: Semgrep's raw-SQL rule

_LIST = "/exchange-accounts/{accountId}/profiles"
_ITEM = _LIST + "/{profileId}"
_PATHS, _COMPONENTS = SPEC["paths"], SPEC["components"]
_CODES = {entry["code"]: entry for entry in SPEC["x-error-codes"]}
_REJECTED = _COMPONENTS["responses"]["ProfileRejected"]
_UNAVAILABLE = _COMPONENTS["responses"]["ProfileSaveUnavailable"]
_OPS = {
    "listAccountProfiles": _PATHS[_LIST]["get"],
    "createAccountProfile": _PATHS[_LIST]["post"],
    "getAccountProfile": _PATHS[_ITEM]["get"],
    "updateAccountProfile": _PATHS[_ITEM]["put"],
    "deleteAccountProfile": _PATHS[_ITEM]["delete"],
}
_WRITES = ("createAccountProfile", "updateAccountProfile", "deleteAccountProfile")
_READ = "401:Unauthorized 403:Forbidden 404:NotFound"
_WRITE = f"{_READ} 409:Conflict 503:ProfileSaveUnavailable"
_STALE, _REFUSED = "412:PreconditionFailed 428:PreconditionRequired", "422:ProfileRejected"
_KEYED = "IdempotencyKey CsrfToken"
_TAGGED = f"IfMatchRequired {_KEYED}"  # a replace or delete of risk caps needs the current `ETag`
#: operationId -> (answers `status[:component]`, a bare status is inline; parameters; idempotency)
_DECLARED = {
    "listAccountProfiles": (f"200 {_READ} 503:ServiceUnavailable", "", None),
    "createAccountProfile": (f"201 {_REFUSED} {_WRITE}", _KEYED, "recommended"),
    "getAccountProfile": (f"200 {_READ} 503:ServiceUnavailable", "", None),
    "updateAccountProfile": (f"200 {_STALE} {_REFUSED} {_WRITE}", _TAGGED, "optional"),
    "deleteAccountProfile": (f"204 {_STALE} {_WRITE}", _TAGGED, "optional"),
}


def _ref(node: dict[str, object]) -> str:
    """The component a `$ref` names, `""` for an inline node."""
    return str(node["$ref"]).rsplit("/", 1)[1] if "$ref" in node else ""


@pytest.mark.parametrize("name", list(_OPS))
def test_each_operation_declares_exactly_its_answers(name: str) -> None:
    op, (answers, _, idempotency) = _OPS[name], _DECLARED[name]
    declared = dict(answer.partition(":")[::2] for answer in answers.split())
    assert {status: _ref(answer) for status, answer in op["responses"].items()} == declared
    assert op.get("x-idempotency") == idempotency
    assert op["x-rbac"]["permissions"] == ["accounts:write" if name in _WRITES else "accounts:read"]
    assert _text(op["description"]).startswith("Owner only") is (name in _WRITES)  # R1S-08 (#4083)


def test_each_operation_takes_exactly_its_parameters() -> None:
    taken = {name: [_ref(p) for p in op.get("parameters", [])] for name, op in _OPS.items()}
    assert taken == {name: params.split() for name, (_, params, _) in _DECLARED.items()}
    assert [_ref(p) for p in _PATHS[_LIST]["parameters"]] == ["AccountId"]
    assert [_ref(p) for p in _PATHS[_ITEM]["parameters"]] == ["AccountId", "ProfileId"]


def _headers(name: str, status: str) -> dict[str, str]:
    declared = _OPS[name]["responses"][status].get("headers", {})
    return {header: _ref(node) for header, node in declared.items()}


def test_answers_that_carry_a_profile_carry_its_etag_and_replay_marker() -> None:
    etag, replayed = {"ETag": "ProfileETag"}, {"Idempotency-Replayed": "IdempotencyReplayed"}
    assert _headers("createAccountProfile", "201") == etag | replayed
    assert _headers("updateAccountProfile", "200") == etag | replayed
    assert _headers("getAccountProfile", "200") == etag
    assert _headers("deleteAccountProfile", "204") == replayed
    assert _headers("listAccountProfiles", "200") == {}
    pattern = _COMPONENTS["headers"]["ProfileETag"]["schema"]["pattern"]
    weak = 'W/"0b5f6d0e-28a1-4c1e-9e01-000000000001:{}"'
    assert re.fullmatch(pattern, weak.format(3))
    assert not re.fullmatch(pattern, weak.format(3).removeprefix("W/"))  # the strong form
    assert not re.fullmatch(pattern, weak.format(0))  # a version starts at 1
    op = _OPS["listAccountProfiles"]  # one page, no `meta`, no cursor
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert (schema["required"], set(schema["properties"])) == (["items"], {"items"})
    assert "an exemption from C3" in _text(op["description"])


@pytest.mark.parametrize("name", list(_OPS))
def test_writes_need_a_risk_caps_step_up_and_reads_none(name: str) -> None:
    step_up = _PATHS["/auth/step-up"]["post"]["requestBody"]["content"]["application/json"]
    classes = step_up["schema"]["properties"]["action_class"]["enum"]
    words = _text(f"{_OPS[name]['summary']} {_OPS[name]['description']}")
    assert "no-grace" not in words  # `risk_caps` has a grace window
    assert bool(re.search(r"step[-_ ]up", words, re.IGNORECASE)) is (name in _WRITES)
    named = {c for c in classes if f"`{c}`" in words}
    assert named == ({"risk_caps"} if name in _WRITES else set())


def test_every_code_the_operations_cite_is_registered() -> None:
    prose = [op["description"] for op in _OPS.values()]
    prose += [_REJECTED["description"], _UNAVAILABLE["description"]]
    pairs = re.findall(r"`(\d{3}) ([a-z_]+)`", _text(" ".join(prose)))
    cited = {(int(status), code) for status, code in pairs}
    codes = {code for _, code in cited}
    assert {"step_up_required", "conflict", "version_conflict", "audit_unavailable"} <= codes
    assert "precondition_required" in codes  # the 428 of a replace or delete without `If-Match`
    # The registry has `validation_failed` at 400, the order routes' status; the profile operations
    # answer 422 as the exchange-accounts routes do (`createApiKey`, `testApiKey`).
    assert _CODES["validation_failed"]["status"] == 400 and (422, "validation_failed") in cited
    wrong = [(s, c) for s, c in cited - {(422, "validation_failed")} if _CODES[c]["status"] != s]
    assert wrong == []
    not_codes = {"precondition_failed", "native_stop_mandatory"}  # the 412 is `version_conflict`
    assert not not_codes & (_CODES.keys() | {code.value for code in ErrorCode})


def test_instrument_cache_unavailable_is_a_retryable_rest_503() -> None:
    entry = _CODES["instrument_cache_unavailable"]
    meta = ERROR_META[ErrorCode.INSTRUMENT_CACHE_UNAVAILABLE]
    assert (entry["status"], entry["retryable"], "surface" in entry) == (503, True, False)
    assert (meta.surfaces, meta.retryable, meta.title) == (("rest",), True, entry["title"])
    generated = (ROOT / "packages/protocol/src/errorCodes.ts").read_text(encoding="utf-8")
    assert '  "instrument_cache_unavailable",\n' in generated  # in the TS list as in `ErrorCode`
    assert _UNAVAILABLE["headers"]["Retry-After"] == {"$ref": "#/components/headers/RetryAfter"}
    examples = _UNAVAILABLE["content"]["application/problem+json"]["examples"]
    shown = examples["instrumentCacheUnavailable"]["value"]
    assert (shown["code"], shown["status"]) == ("instrument_cache_unavailable", 503)
    assert shown["retry_after_seconds"] > 0


def test_precondition_required_is_a_non_retryable_rest_428() -> None:
    entry = _CODES["precondition_required"]
    meta = ERROR_META[ErrorCode.PRECONDITION_REQUIRED]
    assert (entry["status"], entry["retryable"], "surface" in entry) == (428, False, False)
    assert (meta.surfaces, meta.retryable, meta.title) == (("rest",), False, entry["title"])
    generated = (ROOT / "packages/protocol/src/errorCodes.ts").read_text(encoding="utf-8")
    assert '  "precondition_required",\n' in generated  # in the TS list as in `ErrorCode`


def test_profile_refusals_name_the_member_the_symbol_and_the_limit() -> None:
    items = _COMPONENTS["schemas"]["Problem"]["properties"]["errors"]["items"]["properties"]
    assert (_ref(items["symbol"]), _ref(items["limit"])) == ("Symbol", "Decimal")
    assert {"field", "rule", "message", "symbol", "limit"} == set(api.Error.model_fields)
    examples = _REJECTED["content"]["application/problem+json"]["examples"]
    leverage = {"field": "leverage", "rule": "max_leverage", "symbol": "SOLUSDT", "limit": "20"}
    leverage["message"] = "SOLUSDT allows at most 20x — your 25x would be rejected."
    assert examples["leverageAboveExchangeMax"]["value"]["errors"] == [leverage]
    native = examples["nativeStopMandatory"]["value"]
    refusals = [(e["field"], e["rule"]) for e in native["errors"]]
    assert (native["status"], native["code"]) == (422, "validation_failed")
    assert refusals == [("require_native_stop", "native_stop_mandatory")]


@pytest.mark.parametrize(
    ("response", "status"),
    [("ProfileRejected", 422), ("ProfileSaveUnavailable", 503), ("PreconditionRequired", 428)],
)
def test_every_profile_problem_example_is_a_valid_problem(response: str, status: int) -> None:
    content = _COMPONENTS["responses"][response]["content"]
    for name, example in content["application/problem+json"]["examples"].items():
        problem = example["value"]
        validate_example("/components/schemas/Problem", problem)
        assert problem["status"] == status, name  # R1C-06: the status the operations declare
        assert problem["title"] == _CODES[problem["code"]]["title"], name
        assert problem["type"] == f"https://candleviewer.local/errors/{problem['code']}", name


def test_the_refusal_rules_are_one_list_in_two_passes() -> None:
    _, first, second, *_ = [_text(part) for part in _REJECTED["description"].split("\n\n")]
    one = "native_stop_mandatory stop_defines_r required not_allowed range precision ladder_sum"
    one += " above_leverage_cap cap_unbounded default_has_own_operation"
    two = "max_leverage min_order_qty qty_step min_notional symbol_not_listed"
    assert [rule for rule in one.split() if f"`{rule}`" not in first] == []
    assert [rule for rule in two.split() if f"`{rule}`" not in second or f"`{rule}`" in first] == []
    assert "the second only when the first passes" in first
    # R1S-05 (#4083): a pattern that matches every listed symbol allows what `all_symbols` does.
    assert "a universal pattern such as `*USDT` counts as `all_symbols`" in second
    # The unbounded cap is a cap removed rather than raised (PF-T02, R1S-04): audited, and one name.
    assert "a cap removed rather than raised (PF-T02)" in _text(_REJECTED["description"])
    for name in ("ProfileRiskCaps", "AccountProfileInput"):
        assert "`cap_unbounded`" in _text(_COMPONENTS["schemas"][name]["description"])
    # It covers every bound `ap_trading_caps` requires, not the loss caps alone (R4-02, #4087).
    assert "`cap_unbounded` and `default_has_own_operation`." in first  # listed in the first pass
    unbounded = "a trading-enabled profile with a loss-bounding cap left unbounded"
    assert f"{unbounded} (`ap_trading_caps`, decision D11)" in first
    caps = _text(_COMPONENTS["schemas"]["ProfileRiskCaps"]["description"])
    bounds = ["`max_open_positions`", "`max_concurrent_orders`", "`max_leverage_cap`"]
    assert [bound for bound in [*bounds, "position size", "daily loss"] if bound not in caps] == []
    audited = "`native_stop_mandatory`, `above_leverage_cap`, `cap_unbounded` and every refusal"
    assert second.endswith(f"{audited} of the second pass are audited as `profile.save_refused`.")
    # R2S-03: these are Slice A's `PROFILE_SAVE_REFUSED_REASONS` (#4087), no more and no fewer.
    assert set(re.findall(r"`(\w+)`", audited)) | set(two.split()) == PROFILE_SAVE_REFUSED_REASONS
    r4_03 = (  # the 08:08Z ruling: a refusal of shape alone is a 422 and no audit row
        "A body refused only by rules of shape, including semantic shape such as `stop_defines_r`,"
        " is not audited, nor is one refused only by `default_has_own_operation`."
    )
    assert r4_03 in _text(_REJECTED["description"])


def test_a_put_replaces_the_whole_profile_and_says_what_omitting_risk_caps_does() -> None:
    put = _text(_OPS["updateAccountProfile"]["description"])
    sentence = "omitting `risk_caps` clears every cap and resets `max_orders_per_minute` to its "
    assert "A PUT replaces the whole profile" in put
    assert sentence + "server default of 30; send the full object" in put
    assert "`native_stop_mandatory`, audited as `profile.save_refused` (SR-E28-08)" in put


def test_a_stale_if_match_is_version_conflict() -> None:
    stale = _COMPONENTS["responses"]["PreconditionFailed"]["content"]["application/problem+json"]
    assert stale["examples"]["stale"]["value"]["code"] == "version_conflict"
    for name in ("updateAccountProfile", "deleteAccountProfile"):
        assert "`412 version_conflict`" in _text(_OPS[name]["description"])
    doc = AccountVersionConflictError.__doc__ or ""
    assert "version_conflict" in doc and "precondition_failed" not in doc


def _users(parameter: str) -> set[str]:
    """The operations anywhere in the contract that take the component parameter."""
    ref, methods = f"#/components/parameters/{parameter}", ("get", "post", "put", "patch", "delete")
    return {
        op["operationId"]
        for item in _PATHS.values()
        for method, op in item.items()
        if method in methods and any(p.get("$ref") == ref for p in op.get("parameters", []))
    }


def test_a_replace_or_delete_of_risk_caps_needs_the_current_etag() -> None:
    needed, shared = (_COMPONENTS["parameters"][name] for name in ("IfMatchRequired", "IfMatch"))
    assert [(p["name"], p["in"], p["required"]) for p in (needed, shared)] == [
        ("If-Match", "header", True),
        ("If-Match", "header", False),  # every other user of `If-Match` keeps this one
    ]
    assert _users("IfMatchRequired") == {"updateAccountProfile", "deleteAccountProfile"}
    assert not _users("IfMatch") & set(_OPS)
    said = _text(needed["description"])
    assert "needs the current `ETag`: last-write-wins is refused by contract" in said
    assert "`428 precondition_required`" in said
    # R2S-01: no form of the header matches every version, as RFC 9110 lets `*` do
    forms = "`*`, a list of tags, an unparseable value or another profile's tag"
    assert f"one `ETag` of this resource: {forms} is `412 version_conflict`, never a match" in said
    put = _text(_OPS["updateAccountProfile"]["description"])
    delete = _text(_OPS["deleteAccountProfile"]["description"])
    assert "a replace needs the current `ETag`" in put
    assert "a delete needs the current `ETag`" in delete
    assert all("`428 precondition_required`" in words for words in (put, delete))
    assert "last write wins" not in f"{put} {delete}"  # "Without `If-Match` the last write wins"


def test_the_texts_say_who_may_write_and_hide_out_of_grant_accounts() -> None:
    post, listed, got = (
        _text(_OPS[name]["description"])
        for name in ("createAccountProfile", "listAccountProfiles", "getAccountProfile")
    )
    owner = "`accounts:write` is held by the Owner role alone, so no grant on an account gives a"
    assert f"{owner} Manager this write" in post  # R1S-08 (#4083)
    order = "so a Manager meets the step-up first and `403 forbidden` after one"
    assert f"The write is path-gated, as the key routes are, {order}" in post  # 06:01Z, R1C-01
    # R1S-05: out of the caller's grants answers as missing, so a 404 is no existence oracle
    hidden = "outside the caller's grants"
    assert f"An account {hidden} is `404`, as one that does not exist is" in listed
    assert f"of an account {hidden} or missing is `404`, all alike" in got


def test_a_profile_write_never_moves_the_default() -> None:
    """The 09:38Z ruling: the default binding gets its own operation in slice 0d (finding F-31)."""
    put, post = (_text(_OPS[f"{v}AccountProfile"]["description"]) for v in ("update", "create"))
    schemas = _COMPONENTS["schemas"]
    member = _text(schemas["AccountProfileInput"]["properties"]["is_default"]["description"])
    own = "the default binding moves only through its own operation (#906 slice 0d)"
    assert [words for words in (put, post, member) if own not in words] == []
    assert "`422 validation_failed` / `default_has_own_operation`; one that repeats it" in put
    assert "so `is_default: true` is refused (`default_has_own_operation`)" in post
    assert "is refused (`default_has_own_operation`)" in member
    assert 'is "The default binding has its own operation."' in _text(_REJECTED["description"])
    said = " ".join(op["description"] for op in _OPS.values())
    assert not re.search(r"profile\.(un)?bound", said)  # the records of slice 0d's operation
    note = (
        "Not honoured: an account's default profile moves only through the default binding's own"
        " operation (#906 slice 0d); this member is dropped at E27's next contract touch (#895)."
    )
    account = schemas["UpdateExchangeAccountRequest"]["properties"]["active_profile_id"]
    assert _text(account["description"]) == note
    model = ROOT / "docs/security/threat-models/E28-profiles-trade-groups.md"
    rows = [r for r in model.read_text(encoding="utf-8").splitlines() if r.startswith("| F-")]
    owed = [row for row in rows if "#906 0d" in row.split("|")[-2]]  # in its Tracked cell
    owes = "own operation, with its `ETag`, `IfMatchRequired` and the `relaxing` label plus Owner"
    assert len(owed) == 1 and f"the default binding's {owes} notice (SR-E28-01)" in owed[0]
