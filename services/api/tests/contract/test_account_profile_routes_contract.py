"""Contract (#906, E28-T02 slices 0c and 0d-1): the profile and default-binding operations declare
their answers and errors."""

from __future__ import annotations

import re

import pytest
import yaml
from jsonschema import ValidationError

from candleviewer.accounts.errors import AccountVersionConflictError
from candleviewer.accounts.profile_validator import SECOND_PASS_RULES
from candleviewer.api._generated import openapi_models as api
from candleviewer.audit.actions import AUDIT_ACTIONS, PROFILE_SAVE_REFUSED_REASONS
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.contract import _admin_support as support
from tests.contract._admin_support import ROOT, SPEC, validate_example
from tests.contract._admin_support import text as _text  # not `text`: Semgrep's raw-SQL rule

_LIST = "/exchange-accounts/{accountId}/profiles"
_ITEM = _LIST + "/{profileId}"
_BINDING = "/exchange-accounts/{accountId}/default-profile"  # #906 0d
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
    "getAccountDefaultProfile": _PATHS[_BINDING]["get"],
    "setAccountDefaultProfile": _PATHS[_BINDING]["put"],
}
_WRITES: tuple[str, ...] = ("createAccountProfile", "updateAccountProfile", "deleteAccountProfile")
_WRITES += ("setAccountDefaultProfile",)
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
    "getAccountDefaultProfile": (f"200 {_READ} 503:ServiceUnavailable", "", None),
    "setAccountDefaultProfile": (f"200 {_STALE} 422 {_WRITE}", _TAGGED, "optional"),
}
_ZERO_RULE = (  # 11:57Z: the judgement and its two examples, in the contract and 24 Sec.15.5 alike
    "every cap of a profile that cannot trade (`enabled` or `trading_enabled` false) counts as"
    " zero, since it sizes nothing",  # R1C-04 (a): false, never "unset"
    "`allowed_symbols` is not compared",  # O4: caps only
    "onto the bootstrap `Default` while it cannot trade is not relaxing, even with `null` caps",
    "a move that turns trading on, from a default that cannot trade, is always relaxing",
)


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
    assert [_ref(p) for p in _PATHS[_BINDING]["parameters"]] == ["AccountId"]


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
    said = _text(_COMPONENTS["headers"]["ProfileETag"]["description"])
    assert "the server compares the id and the version it names" in said  # R3-04 (iii)
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
    said = _text(_UNAVAILABLE["description"])  # R1S-04: a profile save's alone, never the move's
    assert "(`createAccountProfile` and `updateAccountProfile` only)" in said
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
    assert "the second only when the first passes. The first needs no exchange data:" in first
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
    # R3-02: `two` is the contract's second pass, its backticked rules up to the audited sentence
    # less the members it cites, so a rule added there (and so audited) fails the tie above.
    members = set(_COMPONENTS["schemas"]["AccountProfileInput"]["properties"])
    cited = set(re.findall(r"`([a-z]+(?:_[a-z]+)*)`", second[: second.rindex(audited)]))
    assert cited - members == set(two.split())
    assert set(two.split()) == SECOND_PASS_RULES
    r4_03 = (  # the 08:08Z ruling: a refusal of shape alone is a 422 and no audit row
        "A body refused only by rules of shape or by `default_has_own_operation` is not audited,"
        " semantic shape such as `stop_defines_r` included."
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
    for name in ("updateAccountProfile", "deleteAccountProfile", "setAccountDefaultProfile"):
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
    assert _users("IfMatchRequired") == set(_WRITES) - {"createAccountProfile"}
    assert not _users("IfMatch") & set(_OPS)
    said = _text(needed["description"])
    assert "needs the current `ETag`: last-write-wins is refused by contract" in said
    assert "`428 precondition_required`" in said
    # R2S-01: no form of the header matches every version, as RFC 9110 lets `*` do
    forms = "`*`, a list of tags, an unparseable value or another resource's tag (another"
    forms += " profile's, a profile's sent to the default binding, or another account's"
    forms += " binding tag)"  # R1S-03
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
    """The 09:38Z ruling: the default binding moves only through its own operation,
    `setAccountDefaultProfile` (finding F-31), and no profile text lets a write set it (R3-03)."""
    said = {n: _text(op["description"]) for n, op in _OPS.items() if "Default" not in n}
    put, post, delete = (said[f"{v}AccountProfile"] for v in ("update", "create", "delete"))
    schemas = _COMPONENTS["schemas"]
    member = _text(schemas["AccountProfileInput"]["properties"]["is_default"]["description"])
    own = "the default binding moves only through its own operation (`setAccountDefaultProfile`)"
    assert [words for words in (put, post, member) if own not in words] == []
    assert "`422 validation_failed` / `default_has_own_operation`; one that repeats it" in put
    assert "so `is_default: true` is refused (`default_has_own_operation`)" in post
    assert "is refused (`default_has_own_operation`)" in member
    assert 'is "The default binding has its own operation."' in _text(_REJECTED["description"])
    assert not re.search(r"profile\.(un)?bound", " ".join(said.values()))  # the binding's records
    # R3-03 (X1, X9): a clause on the default that says what sets it refuses the write or names the
    # binding's own operation, and none lets a write set it; X4: the delete's blocker stays
    clauses = [c for words in [*said.values(), member] for c in re.split(r"[.;:] |,? but ", words)]
    about = [c for c in clauses if re.search(r"\bdefault\b|`is_default", c)]
    lets = re.compile(r"\b(?:may|can|could|will)\b|`is_default: true` (?!is refused)")
    sets = re.compile(r"\b(?:sets?|makes?|moves?|changes?|becomes?)\b")
    refuses = ("never", "refused", "only through its own operation", "`setAccountDefaultProfile`")
    assert len(about) >= 6 and [c for c in about if lets.search(c)] == []
    assert [c for c in about if sets.search(c) and not any(r in c for r in refuses)] == []
    blocker = "while the profile is the account's default (make another profile the default first,"
    assert f"{blocker} with `setAccountDefaultProfile`)" in delete  # R1C-04 (d)(i), O15
    note = (
        "Not honoured: a value sent is ignored, since an account's default profile moves only"
        " through the default binding's own operation (`setAccountDefaultProfile`); this member is"
        " dropped at E27's next contract touch (#895)."
    )
    account = schemas["UpdateExchangeAccountRequest"]["properties"]["active_profile_id"]
    assert _text(account["description"]) == note
    assert "profile" not in _PATHS["/exchange-accounts/{accountId}"]["patch"]["summary"]  # R3-04
    model = ROOT / "docs/security/threat-models/E28-profiles-trade-groups.md"
    lines = model.read_text(encoding="utf-8").splitlines()
    rows = [r for r in lines if r.startswith("| F-")]
    owed = [row for row in rows if "#906 0d" in row.split("|")[-2]]  # in its Tracked cell
    owes = "`setAccountDefaultProfile`, with its own `ETag` and `IfMatchRequired` (#906 0d)"
    route = "Owed: the route that writes `profile.bound` with the `relaxing` label and notifies the"
    assert len(owed) == 1 and owes in owed[0] and f"{route} Owner (SR-E28-01)" in owed[0]
    # R3-03 (X3), R3-04 (vi), O9: Medium, a schema finding (the binding's version), due before D2
    cells = [cell.strip() for cell in owed[0].split("|")[4:8]]
    assert cells == ["Medium", "yes", "Backend lead", "Before #906 D2 mounts"]
    # O10, O14 (R1S-05): SR-E28-02 gates the binding's PUT and prefix; PF-T02 is refused on it too
    (gated,) = [r for r in lines if r.startswith("| SR-E28-02 ")]
    assert "the default binding's `PUT`" in gated and "{id}/default-profile`" in gated
    assert any(r.startswith("| PF-T02 ") and "and the default binding (F-31)" in r for r in lines)


# -- #906 0d: the default binding -----------------------------------------------------------------


def test_the_binding_answers_carry_its_etag_and_the_move_its_replay_marker() -> None:
    tag, replayed = {"ETag": "DefaultBindingETag"}, {"Idempotency-Replayed": "IdempotencyReplayed"}
    assert _headers("getAccountDefaultProfile", "200") == tag
    assert _headers("setAccountDefaultProfile", "200") == tag | replayed
    for name in ("getAccountDefaultProfile", "setAccountDefaultProfile"):
        answer = _OPS[name]["responses"]["200"]["content"]["application/json"]["schema"]
        assert _ref(answer) == "AccountDefaultBinding", name
    bound = 'W/"a1000000-0000-4000-8000-000000000001:default:3"'
    others = [bound[2:], bound.replace(":3", ":0"), 'W/"0b5f6d0e-28a1-4c1e-9e01-000000000001:3"']
    pattern = _COMPONENTS["headers"]["DefaultBindingETag"]["schema"]["pattern"]
    assert [t for t in [bound, *others] if re.fullmatch(pattern, t)] == [bound]  # nor a profile's
    assert not re.fullmatch(_COMPONENTS["headers"]["ProfileETag"]["schema"]["pattern"], bound)
    said = _text(_COMPONENTS["headers"]["DefaultBindingETag"]["description"])  # O2, R1C-04 (c)
    assert "never the profile it names, so a tag read before a move never matches after it" in said
    assert "the server compares the account id and the version it names" in said


def test_the_move_body_names_the_profile_and_nothing_else() -> None:
    """The 11:04Z point: the caller names the profile, the server judges; test 6 folded in."""
    schema = _COMPONENTS["schemas"]["AccountDefaultBindingInput"]
    shape = (schema["additionalProperties"], schema["required"], list(schema["properties"]))
    assert shape == (False, ["profile_id"], ["profile_id"])
    model = api.AccountDefaultBindingInput
    assert (model.model_config.get("extra"), set(model.model_fields)) == ("forbid", {"profile_id"})
    put = _OPS["setAccountDefaultProfile"]
    assert put["requestBody"]["required"] is True  # O1: else the generated body is optional
    body = put["requestBody"]["content"]["application/json"]
    assert _ref(body["schema"]) == "AccountDefaultBindingInput"
    pointer, example = "/components/schemas/AccountDefaultBindingInput", body["examples"]
    validate_example(pointer, example["bindAlternate"]["value"])
    with pytest.raises(ValidationError):
        validate_example(pointer, {**example["bindAlternate"]["value"], "relaxing": False})
    assert "the server's judgement" in _text(schema["description"])
    refused = put["responses"]["422"]
    problem = refused["content"]["application/problem+json"]["examples"]["notAProfileId"]["value"]
    validate_example("/components/schemas/Problem", problem)
    shown = (problem["status"], problem["code"], problem["title"])
    assert shown == (422, "validation_failed", _CODES["validation_failed"]["title"])
    refusals = [(e["field"], e["rule"]) for e in problem["errors"]]
    assert refusals == [("body.profile_id", "uuid_parsing")]
    assert "nothing is audited" in _text(refused["description"])


def test_the_binding_is_a_profile_id_and_a_version_that_never_repeats() -> None:
    schema = _COMPONENTS["schemas"]["AccountDefaultBinding"]
    assert schema["required"] == ["exchange_account_id", "profile_id", "version"]
    assert schema["properties"]["version"] == {"type": "integer", "minimum": 1}
    assert "grows by one with each move, so it never repeats" in _text(schema["description"])
    answer = _OPS["getAccountDefaultProfile"]["responses"]["200"]["content"]["application/json"]
    bound = answer["examples"]["bound"]["value"]
    validate_example("/components/schemas/AccountDefaultBinding", bound)
    assert set(api.AccountDefaultBinding.model_fields) == set(schema["properties"])


def test_a_stale_tag_never_moves_the_default_and_a_lost_answer_replays() -> None:
    put = _text(_OPS["setAccountDefaultProfile"]["description"])
    said = (
        "takes this binding's `ETag`, never a profile's, and it is checked before the profile",
        "`412 version_conflict`, even when the default has since come back to the profile it was",
        "answered from the stored `200` before `If-Match` is read",
        "deleted or another account's is `404`, as an account outside the caller's grants is",
        "the key with another body is `409 idempotency_key_reuse`",  # R1S-05
    )
    assert [words for words in said if words not in put] == []
    got = _text(_OPS["getAccountDefaultProfile"]["description"])
    assert "outside the caller's grants is `404`, all alike" in got


def test_a_move_is_audited_unbound_then_bound_and_a_looser_cap_is_relaxing() -> None:
    """SR-E28-01; 11:57Z: the zero rule's examples in 22 and 24 alike, so UI and audit agree."""
    put = _text(_OPS["setAccountDefaultProfile"]["description"])
    said = (
        "as `profile.unbound` for the default it replaces, then `profile.bound` for the new one",
        "(`503 audit_unavailable`)",
        "`profile.bound` is labelled `relaxing` and the Owner is notified (SR-E28-01)",
        "Binding the profile that already is the default changes nothing, writes no record",
    )
    assert [words for words in (*said, *_ZERO_RULE) if words not in put] == []
    assert {"profile.bound", "profile.unbound"} <= AUDIT_ACTIONS
    doc = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8").splitlines()
    lead = "The `profile.*` records (E28-T02, #906)"
    (records,) = [line for line in doc if line.startswith(lead)]
    kept = (
        "`setAccountDefaultProfile`",
        "`relaxing`",
        "`looser_caps`",
        "`default_profile_id` and `binding_version` in both `before` and `after`",  # O3
        "Binding the profile that already is the default writes neither record",  # R1S-05
    )
    assert [words for words in (*kept, *_ZERO_RULE) if words not in records] == []
    assert "A `PUT` with `is_default: true`" not in records


def test_the_move_is_the_owners_alone_in_both_matrices() -> None:
    matrix = ROOT / "services/api/tests/contract/rbac/matrix.yaml"
    rows = yaml.safe_load(matrix.read_text(encoding="utf-8"))["operations"]
    assert rows[f"PUT {_BINDING}"]["outcomes"] == support.OWNER_ONLY
    assert rows[f"GET {_BINDING}"]["outcomes"] == rows[f"GET {_LIST}"]["outcomes"]
    _, cell, *granted = support.capability_rows()["21c"]
    assert support.grants(cell) == ({"accounts:write"}, {"setAccountDefaultProfile"})
    assert granted == ["✔(step-up)", "✖", "✖"]
