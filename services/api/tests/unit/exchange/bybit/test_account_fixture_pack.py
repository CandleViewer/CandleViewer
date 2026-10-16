"""E27-Q01 (#833): every accounts fault-injection scenario through the shipped adapter and pipeline.

Each scenario (`packages/fixtures/accounts/`, loaded by `tests/_account_fixtures.py`) is served
to the adapter's own REST client by an `httpx.MockTransport`: no socket, no network (C-13.5). The
replies are parsed by `key_info.py` (`parse_key_info`, `parse_probe`, `refusal`), classified by
`mapping.py` and judged by the shipped permission gates (M13 deny-list, M2 allow-list and
deny-list) and by the shipped verification pipeline (`accounts.verification.verify`, E27-T03,
#2854). Its two sources call the adapter here and map its errors the way
`tests/unit/accounts/test_key_verification.py` does, standing in for the production wiring that
E27-T03 has not shipped yet. Every key scenario's recorded verdict is asserted against the
pipeline's. The plan rows the pipeline does not produce yet are pinned (`PLAN_AHEAD_OF_PIPELINE`,
`AC15_SHARED_RULE`); the one row judged outside it by design is `JUDGED_OUTSIDE_THE_PIPELINE`.
Unconfirmed refusal codes are compared with the scenario's own reply, never with a literal.
Times are anchored on a frozen `NOW`; nothing sleeps. Each request is asserted to be signed with
the scenario's key id. Its host is the one these tests point the client at, so the host check is a
smoke check only, never evidence of demo/live isolation (C-2.11): that proof is #2893's request
log (test plan section 9.6).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, NoReturn
from uuid import UUID

import httpx
import pytest
from jsonschema import Draft202012Validator

from candleviewer.accounts._permissions import reject_withdraw as m13_reject_withdraw
from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.accounts.models import AccountKind, ExchangeAccount, ExchangeEnv
from candleviewer.accounts.verification import (
    KeyRefused,
    Refusal,
    Rule,
    VerificationInconclusive,
    VerificationPolicy,
    VerificationResult,
    verify,
)
from candleviewer.exchange.base.errors import (
    AuthError,
    ClockDriftError,
    ExchangeError,
    RateLimitError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.key_info import (
    KEY_INFO_PATH,
    PROBE_PATH,
    ApiKeyFacts,
    ProbeFacts,
    parse_key_info,
    parse_probe,
    refusal,
)
from candleviewer.exchange.bybit.models import ServerTime
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient, validate_rest_path
from candleviewer.exchange.bybit.signer import BybitSigner
from candleviewer.secrets._permissions import reject_withdraw as m2_reject_withdraw
from candleviewer.secrets._permissions import require_allow_listed
from candleviewer.secrets.errors import WithdrawPermissionRejected
from tests._account_fixtures import (
    ACCOUNT_PARENTS,
    EGRESS_IP,
    OVERLAY,
    PACK_ROOT,
    WILDCARD,
    Scenario,
    UnstubbedCall,
    _payload,
    load,
    load_rotation,
    manifest,
    merge_patch,
    scenario_names,
    schema,
)
from tests._signing import CREDENTIAL_ID, fake_capability

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
NOW_MS = 1_792_141_200_000
DAY = timedelta(days=1)
DEMO_HOST = "api-demo.bybit.com"
ROTATIONS = ("rotation_ok", "rotation_new_key_withdraw")
OVERLAYS = ("open_position_btcusdt_5x_sl", "working_orders_2", "history_round_trip")
MODE_SWITCHES = (
    ("POST", "/v5/position/switch-mode", EndpointClass.POSITION),
    ("POST", "/v5/position/switch-isolated", EndpointClass.POSITION),
    ("POST", "/v5/account/set-margin-mode", EndpointClass.ACCOUNT),
)
ORDER_BODY: Final = {"category": "linear", "symbol": "BTCUSDT", "orderLinkId": "fixture-order-0001"}

#: Test plan section 9.3: 46 scenarios and 3 overlays; the JS lane pins the same list
#: (packages/fixtures/test).
PLAN_SCENARIOS = {
    "compliant", "compliant_alt", "withdraw_enabled", "transfer_enabled", "subtransfer_enabled",
    "subtransfer_list_enabled", "fiat_p2p_enabled", "fiat_bitpay_enabled",
    "fiat_convert_broker_enabled", "bitcard_enabled", "ip_missing", "ip_mismatch",
    "ip_extra_foreign", "ip_wildcard", "uid_mismatch", "non_uta", "clock_skew",
    "wallet_probe_error", "missing_trade_scope", "extra_scope_spot", "extra_scope_options",
    "extra_scope_exchange", "extra_scope_nft", "extra_scope_affiliate", "live_key_on_demo",
    "unknown_key", "stored_key_rejected", "demo_ws_unreachable", "expiring_13d", "expiring_15d",
    "expired_key", "new_key_48h", "bybit_5xx", "rate_limited_10018", "ws_auth_timeout",
    "ws_auth_then_drop", "ws_quiet", "ws_quiet_rest_fail", "ws_drop_rest_fail", "ws_blip_20s",
    *ROTATIONS, "key_delete_5xx", "close_rejected", "leverage_ok",
    "leverage_refused_open_position", *OVERLAYS,
}  # fmt: skip
KEY_SCENARIOS = sorted(PLAN_SCENARIOS - set(ROTATIONS) - set(OVERLAYS))

#: The trade-only permission groups of the compliant key-info reply.
TRADE_ONLY: dict[str, Any] = {
    "ContractTrade": ["Order", "Position"], "Spot": [], "Wallet": [], "Options": [],
    "Derivatives": ["DerivativesTrade"], "CopyTrading": [], "BlockTrade": [], "Exchange": [],
    "NFT": [], "Affiliate": [], "Earn": [],
}  # fmt: skip
COMPLIANT = ApiKeyFacts(
    uid="90000001",
    unified=True,
    read_only=False,
    permissions=TRADE_ONLY,
    ip_whitelist=(EGRESS_IP,),
    expires_at=NOW + 365 * DAY,
)


def facts(**change: Any) -> ApiKeyFacts:
    return dataclasses.replace(COMPLIANT, **change)


def rights(**groups: list[str]) -> dict[str, Any]:
    return {**TRADE_ONLY, **groups}


#: Rights in the Wallet group: every deny-list layer refuses them too (C-2.8, SR-030a).
FUND_RIGHTS = {
    "withdraw_enabled": rights(Wallet=["Withdraw"]),
    "transfer_enabled": rights(Wallet=["AccountTransfer"]),
    "subtransfer_enabled": rights(Wallet=["SubMemberTransfer"]),
    "subtransfer_list_enabled": rights(Wallet=["SubMemberTransferList"]),
}
#: Rights only the allow-list refuses: no withdraw or transfer in the name (#2270, SR-030a).
OUTSIDE_ALLOW_LIST = {
    "fiat_p2p_enabled": rights(FiatP2P=["FiatP2POrder"]),
    "fiat_bitpay_enabled": rights(FiatBitPay=["FaitPayOrder"]),
    "fiat_convert_broker_enabled": rights(FiatConvertBroker=["FiatConvertBroker"]),
    "bitcard_enabled": rights(BitCard=["BitCard"]),
    "extra_scope_spot": rights(Spot=["SpotTrade"]),
    "extra_scope_options": rights(Options=["OptionsTrade"]),
    "extra_scope_exchange": rights(Exchange=["ExchangeHistory"]),
    "extra_scope_nft": rights(NFT=["NFT"]),
    "extra_scope_affiliate": rights(Affiliate=["Affiliate"]),
}

#: What the key-info call yields through the adapter: the parsed facts, or the error class.
#: `stored_key_rejected` is shown before its runtime switch.
KEY_INFO: dict[str, ApiKeyFacts | type[ExchangeError]] = {
    "compliant": COMPLIANT,
    "compliant_alt": COMPLIANT,
    **{name: facts(permissions=p) for name, p in {**FUND_RIGHTS, **OUTSIDE_ALLOW_LIST}.items()},
    "ip_missing": facts(ip_whitelist=()),
    "ip_mismatch": facts(ip_whitelist=("198.51.100.20",)),
    "ip_extra_foreign": facts(ip_whitelist=(EGRESS_IP, "192.0.2.30")),
    "ip_wildcard": facts(ip_whitelist=(WILDCARD,)),
    "uid_mismatch": facts(uid="90000099"),
    "non_uta": facts(unified=False),
    "clock_skew": COMPLIANT,
    "wallet_probe_error": COMPLIANT,
    "missing_trade_scope": facts(permissions=rights(ContractTrade=[])),
    "live_key_on_demo": AuthError,
    "unknown_key": AuthError,
    "stored_key_rejected": COMPLIANT,
    "demo_ws_unreachable": COMPLIANT,
    "expiring_13d": facts(expires_at=NOW + 13 * DAY),
    "expiring_15d": facts(expires_at=NOW + 15 * DAY),
    "expired_key": facts(expires_at=NOW - DAY),
    "new_key_48h": COMPLIANT,
    "bybit_5xx": TransportError,
    "rate_limited_10018": RateLimitError,
    "ws_auth_timeout": COMPLIANT,
    "ws_auth_then_drop": COMPLIANT,
    "ws_quiet": COMPLIANT,
    "ws_quiet_rest_fail": COMPLIANT,
    "ws_drop_rest_fail": TransportError,
    "ws_blip_20s": COMPLIANT,
    "key_delete_5xx": facts(uid="90000011"),
    "close_rejected": facts(uid="90000011"),
    "leverage_ok": COMPLIANT,
    "leverage_refused_open_position": COMPLIANT,
}

#: Signed-probe failures: (error class, the `refusal()` reason, `None` when it is no verdict).
#: The code is compared with the scenario's own reply. Every other key scenario's probe succeeds.
PROBE_FAILS: dict[str, tuple[type[ExchangeError], str | None]] = {
    "clock_skew": (ClockDriftError, None),
    "wallet_probe_error": (AuthError, "permission_denied"),
    "live_key_on_demo": (AuthError, "unknown_key"),
    "unknown_key": (AuthError, "unknown_key"),
    "bybit_5xx": (TransportError, None),
    "rate_limited_10018": (RateLimitError, None),
    "ws_quiet_rest_fail": (TransportError, None),
    "ws_drop_rest_fail": (TransportError, None),
}

#: Every reply the pack flags `code_unconfirmed` (README): a new flag is added here on purpose.
UNCONFIRMED = {
    ("wallet_probe_error", "GET /v5/account/wallet-balance"),
    ("close_rejected", "POST /v5/order/create"),
    ("leverage_refused_open_position", "POST /v5/position/set-leverage"),
    *(
        (overlay, f"{method} {path}")
        for overlay in ("open_position_btcusdt_5x_sl", "working_orders_2")
        for method, path, _ in MODE_SWITCHES
    ),
}

#: A pipeline outcome in the manifests' words: the verdict, with the failing rules of a refusal
#: or the warnings of a pass.
Verdict = tuple[str, tuple[str, ...]]
PASSED: Final[Verdict] = ("passed", ())
INCONCLUSIVE: Final[Verdict] = ("inconclusive", ())


def refused(rule: Rule) -> Verdict:
    return ("refused", (rule.value,))


#: What the shipped pipeline concludes for each key scenario when it is loaded
#: (`stored_key_rejected` after its runtime switch).
PIPELINE: dict[str, Verdict] = {
    "compliant": PASSED,
    "compliant_alt": PASSED,
    **dict.fromkeys(FUND_RIGHTS, refused(Rule.WITHDRAW_PERMISSION)),
    **dict.fromkeys(OUTSIDE_ALLOW_LIST, refused(Rule.WITHDRAW_PERMISSION)),
    "ip_missing": refused(Rule.IP_WHITELIST_MISSING),
    "ip_mismatch": refused(Rule.IP_WHITELIST_MISMATCH),
    "ip_extra_foreign": refused(Rule.IP_WHITELIST_MISMATCH),
    "ip_wildcard": refused(Rule.IP_WHITELIST_MISSING),
    "uid_mismatch": refused(Rule.UID_MISMATCH),
    "non_uta": refused(Rule.NOT_UNIFIED),
    "clock_skew": INCONCLUSIVE,
    "wallet_probe_error": refused(Rule.PROBE_FAILED),
    "missing_trade_scope": refused(Rule.MISSING_SCOPES),
    "live_key_on_demo": refused(Rule.WRONG_ENVIRONMENT),
    "unknown_key": refused(Rule.WRONG_ENVIRONMENT),
    "stored_key_rejected": refused(Rule.WRONG_ENVIRONMENT),
    "demo_ws_unreachable": PASSED,
    "expiring_13d": ("passed_with_warning", ("key_expires_soon",)),
    "expiring_15d": PASSED,
    "expired_key": refused(Rule.KEY_EXPIRED),
    "new_key_48h": PASSED,
    "bybit_5xx": INCONCLUSIVE,
    "rate_limited_10018": INCONCLUSIVE,
    "ws_auth_timeout": PASSED,
    "ws_auth_then_drop": PASSED,
    "ws_quiet": PASSED,
    "ws_quiet_rest_fail": INCONCLUSIVE,
    "ws_drop_rest_fail": INCONCLUSIVE,
    "ws_blip_20s": PASSED,
    "key_delete_5xx": PASSED,
    "close_rejected": PASSED,
    "leverage_ok": PASSED,
    "leverage_refused_open_position": PASSED,
}

#: Plan verdicts the shipped pipeline does not reach yet: (recorded verdict, why). Pinned, so the
#: day the pipeline produces them this test fails and the entry is removed.
PLAN_AHEAD_OF_PIPELINE: dict[str, tuple[str, str]] = {
    "new_key_48h": (
        "passed_with_warning",
        "verification.py has no 48 h new-key warning code (plan TC-130, DC-23)",
    ),
}

#: E27 threat model AC-15 (test plan section 2): these six inputs are each refused with a rule of
#: their own (TC-103a, TC-103d, TC-104, TC-106a, TC-106b, TC-108).
AC15_INPUTS = (
    "transfer_enabled", "fiat_p2p_enabled", "ip_missing", "ip_extra_foreign", "ip_wildcard",
    "non_uta",
)  # fmt: skip
#: The AC-15 inputs that get an earlier input's rule from the shipped pipeline (#2417). Each
#: records a bare `validation_failed`: its rule is pending and must differ. Pinned, so the day the
#: pipeline separates a pair the AC-15 test fails and the manifest records the new rule.
AC15_SHARED_RULE: dict[str, str] = {
    "fiat_p2p_enabled": "transfer_enabled",
    "ip_wildcard": "ip_missing",
}

#: Plan verdicts judged outside verification.py by design: (recorded verdict, why). Not a pin,
#: since the pipeline can never reach them.
JUDGED_OUTSIDE_THE_PIPELINE: dict[str, tuple[str, str]] = {
    "ws_auth_timeout": (
        "refused",
        "the test route's private-WS probe (plan TC-125); verification.py judges the two signed"
        " REST calls only",
    ),
}


async def _no_sleep(_seconds: float) -> None:
    return None


def _governor() -> TokenBucketGovernor:
    """A governor on a virtual clock: an IP hold after 10018 elapses instantly."""
    now = [0.0]

    async def advance(seconds: float) -> None:
        now[0] += seconds

    return TokenBucketGovernor(
        default_capacity=1000.0, default_refill_per_s=1000.0, clock=lambda: now[0], sleep=advance
    )


async def call(
    scenario: Scenario,
    method: str,
    path: str,
    *,
    endpoint: EndpointClass = EndpointClass.ACCOUNT,
    params: Mapping[str, Any] | None = None,
    body: Mapping[str, Any] | None = None,
    at_ms: int = 0,
    log: list[httpx.Request] | None = None,
) -> dict[str, Any]:
    """One signed call through the adapter's REST client, answered by the scenario."""
    seen = log if log is not None else []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        reply = scenario.reply(request.method, request.url.path, at_ms=at_ms)
        return httpx.Response(reply.status, json=reply.body, headers=dict(reply.headers))

    client = BybitRestClient(
        RestClientConfig(base_url=f"https://{DEMO_HOST}", max_retries=0),
        signer=BybitSigner(fake_capability(scenario.key_id), CREDENTIAL_ID),
        governor=_governor(),
        transport=httpx.MockTransport(answer),
        sleep=_no_sleep,
        wall_clock=lambda: NOW_MS / 1000,
        clock_offset_ms_provider=lambda: 0,
    )
    try:
        return await client.signed_request(
            method, path, params=params, body=body, endpoint_class=endpoint
        )
    finally:
        await client.aclose()


async def key_info(scenario: Scenario) -> ApiKeyFacts:
    return parse_key_info(await call(scenario, "GET", KEY_INFO_PATH))


def _account(uid: str) -> ExchangeAccount:
    """The section 9.2 account the key is stored on."""
    parent = ACCOUNT_PARENTS[uid]
    return ExchangeAccount(
        id=UUID(int=int(uid)),
        env=ExchangeEnv.DEMO,
        kind=AccountKind.MAIN if parent is None else AccountKind.SUB,
        exchange_uid=uid,
        parent_account_id=None if parent is None else UUID(int=int(parent)),
        label=f"fx-{uid}",
        created_at=NOW,
        updated_at=NOW,
    )


def _judge(error: ExchangeError) -> NoReturn:
    """A verdict refusal is `KeyRefused`; anything else is inconclusive (SR-E27-18)."""
    found = refusal(error)
    if found is None:
        raise VerificationInconclusive(type(error).__name__) from None
    raise KeyRefused(Refusal(found[0]), found[1]) from None


async def pipeline(
    scenario: Scenario, log: list[httpx.Request] | None = None
) -> VerificationResult:
    """The shipped seven checks over the scenario's two signed calls through the adapter."""

    async def key_info_source() -> ApiKeyFacts:
        try:
            return parse_key_info(await call(scenario, "GET", KEY_INFO_PATH, log=log))
        except ExchangeError as error:
            _judge(error)

    async def probe_source() -> ProbeFacts:
        params = {"accountType": "UNIFIED"}
        try:
            body = await call(scenario, "GET", PROBE_PATH, params=params, log=log)
            return parse_probe(body, sent_at_ms=NOW_MS, received_at_ms=NOW_MS)
        except ExchangeError as error:
            _judge(error)

    return await verify(
        _account(scenario.account_uid),
        read_only=False,
        key_info=key_info_source,
        probe=probe_source,
        policy=VerificationPolicy(egress_ip=scenario.egress_ip),
        now=NOW,
    )


async def judged(scenario: Scenario) -> Verdict:
    try:
        result = await pipeline(scenario)
    except VerificationInconclusive:
        return INCONCLUSIVE
    if not result.passed:
        return ("refused", tuple(f.rule.value for f in result.failures))
    if result.warnings:
        return ("passed_with_warning", tuple(w.value for w in result.warnings))
    return PASSED


def _with(overlay: str, name: str = "compliant") -> Scenario:
    return load(name, now=NOW, overlays=[overlay])


def test_the_pack_holds_exactly_the_plan_scenarios() -> None:
    assert set(scenario_names()) == PLAN_SCENARIOS
    assert {n for n in scenario_names() if manifest(n)["origin"] == OVERLAY} == set(OVERLAYS)


def test_the_expectation_tables_cover_every_key_scenario() -> None:
    assert sorted(KEY_INFO) == KEY_SCENARIOS
    assert sorted(PIPELINE) == KEY_SCENARIOS
    assert set(PROBE_FAILS) <= set(KEY_SCENARIOS)
    exceptions = [*PLAN_AHEAD_OF_PIPELINE, *AC15_SHARED_RULE, *JUDGED_OUTSIDE_THE_PIPELINE]
    assert len(exceptions) == len(set(exceptions))  # no row sits in two tables
    assert set(exceptions) <= set(KEY_SCENARIOS)
    assert {*AC15_SHARED_RULE.keys(), *AC15_SHARED_RULE.values()} <= set(AC15_INPUTS)
    assert set(AC15_INPUTS) <= set(KEY_SCENARIOS)


@pytest.mark.parametrize("name", sorted(PLAN_SCENARIOS))
def test_manifest_matches_the_schema(name: str) -> None:
    Draft202012Validator.check_schema(schema())
    errors = [e.message for e in Draft202012Validator(schema()).iter_errors(manifest(name))]
    assert errors == []
    assert manifest(name)["scenario"] == name


@pytest.mark.parametrize("name", KEY_SCENARIOS)
async def test_key_info_through_the_adapter(name: str) -> None:
    scenario = load(name, now=NOW)
    log: list[httpx.Request] = []
    expected = KEY_INFO[name]
    if isinstance(expected, ApiKeyFacts):
        assert parse_key_info(await call(scenario, "GET", KEY_INFO_PATH, log=log)) == expected
    else:
        with pytest.raises(expected):
            await call(scenario, "GET", KEY_INFO_PATH, log=log)
    # Smoke only: `call` chose the host. Demo/live isolation is #2893's request log.
    assert {r.url.host for r in log} == {DEMO_HOST}
    assert {r.headers["X-BAPI-API-KEY"] for r in log} == {scenario.key_id}


@pytest.mark.parametrize("name", KEY_SCENARIOS)
async def test_signed_probe_through_the_adapter(name: str) -> None:
    scenario = load(name, now=NOW)
    params = {"accountType": "UNIFIED"}
    if name not in PROBE_FAILS:
        body = await call(scenario, "GET", PROBE_PATH, params=params)
        probe = parse_probe(body, sent_at_ms=NOW_MS, received_at_ms=NOW_MS)
        assert probe.server_time_ms == NOW_MS
        return
    error_class, reason = PROBE_FAILS[name]
    with pytest.raises(error_class) as caught:
        await call(scenario, "GET", PROBE_PATH, params=params)
    sent = scenario.reply("GET", PROBE_PATH).body.get("retCode")
    assert refusal(caught.value) == (None if reason is None else (reason, sent))


@pytest.mark.parametrize("name", KEY_SCENARIOS)
async def test_the_pipeline_judges_each_key_scenario(name: str) -> None:
    switched = "switch_to" in manifest(name)
    assert await judged(load(name, now=NOW, switched=switched)) == PIPELINE[name]


@pytest.mark.parametrize("name", KEY_SCENARIOS)
def test_recorded_verdict_matches_the_pipeline(name: str) -> None:
    """The manifest's plan verdict, and the rule its problem names, are the pipeline's, except
    in the pinned rows and the one judged outside it (README, shipped pipeline vs plan)."""
    expected = manifest(name)["expected"]
    verdict, codes = PIPELINE[name]
    recorded = expected.get("verification")
    elsewhere = {**PLAN_AHEAD_OF_PIPELINE, **JUDGED_OUTSIDE_THE_PIPELINE}
    if name in elsewhere:
        assert (recorded, verdict) == (elsewhere[name][0], "passed")
        return
    assert recorded in (None, verdict)
    problem = str(expected.get("problem", ""))
    if name in AC15_SHARED_RULE:
        assert (problem, verdict) == ("validation_failed", "refused")  # its rule is pending
    elif problem.startswith("validation_failed/"):
        assert (verdict, codes) == ("refused", (problem.removeprefix("validation_failed/"),))


async def test_ac15_inputs_share_a_pipeline_rule_only_in_the_pinned_pairs() -> None:
    """E27 threat model AC-15 wants six rules for its six inputs. The pipeline gives two pairs
    one rule each (#2417); a third shared pair, or a separated one, fails here."""
    verdicts = {name: await judged(load(name, now=NOW)) for name in AC15_INPUTS}
    assert {verdict for verdict, _ in verdicts.values()} == {"refused"}
    shared = {
        (later, earlier)
        for i, later in enumerate(AC15_INPUTS)
        for earlier in AC15_INPUTS[:i]
        if verdicts[later] == verdicts[earlier]
    }
    assert shared == set(AC15_SHARED_RULE.items())


def test_ac15_inputs_record_six_distinct_rules_or_a_pending_one() -> None:
    """The pack, as E27-Q02's oracle, never records one rule for two AC-15 inputs."""
    problems = {name: str(manifest(name)["expected"]["problem"]) for name in AC15_INPUTS}
    pending = {name for name, problem in problems.items() if problem == "validation_failed"}
    assert pending == set(AC15_SHARED_RULE)
    named = [problem for name, problem in problems.items() if name not in pending]
    assert all(problem.startswith("validation_failed/") for problem in named)
    assert len(named) == len(set(named))


@pytest.mark.parametrize(
    ("name", "new_key"),
    [("rotation_ok", PASSED), ("rotation_new_key_withdraw", refused(Rule.WITHDRAW_PERMISSION))],
)
async def test_rotation_pair_through_the_pipeline(name: str, new_key: Verdict) -> None:
    pair = load_rotation(name, now=NOW)
    assert await judged(pair.old) == PASSED
    assert await judged(pair.new) == new_key
    assert pair.expected["verification"] == new_key[0]
    if "problem" in pair.expected:
        assert pair.expected["problem"] == f"validation_failed/{new_key[1][0]}"


async def test_ticket_ac2_withdrawal_key_fails_on_key_info_alone() -> None:
    """Ticket AC 2: `key_withdraw_permission`, and the over-privileged key never signs a probe."""
    log: list[httpx.Request] = []
    result = await pipeline(load("withdraw_enabled", now=NOW), log)
    assert (result.passed, result.withdraw_enabled) == (False, True)
    assert [f.rule for f in result.failures] == [Rule.WITHDRAW_PERMISSION]
    assert [r.url.path for r in log] == [KEY_INFO_PATH]
    assert manifest("withdraw_enabled")["expected"]["problem"] == (
        "validation_failed/key_withdraw_permission"
    )


async def test_stored_key_passes_until_the_runtime_switch_then_is_refused() -> None:
    before = load("stored_key_rejected", now=NOW)
    after = load("stored_key_rejected", now=NOW, switched=True)
    assert await judged(before) == PASSED
    assert await judged(after) == refused(Rule.WRONG_ENVIRONMENT)
    assert before.key_id == after.key_id == "fixture-stored_key_rejected-0046"
    assert (before.ws.on_auth.do, after.ws.on_auth.do) == ("reply", "close")
    assert after.expected == manifest("stored_key_rejected")["expected"]


async def test_unknown_key_answers_exactly_as_live_key_on_demo() -> None:
    unknown, live = load("unknown_key", now=NOW), load("live_key_on_demo", now=NOW)
    assert unknown.stubbed_calls() == live.stubbed_calls()
    for stubbed in sorted(live.stubbed_calls() - {WILDCARD}):
        method, path = stubbed.split(" ", 1)
        assert unknown.reply(method, path) == live.reply(method, path)
    assert unknown.ws == live.ws
    assert unknown.key_id != live.key_id


@pytest.mark.parametrize("name", sorted(FUND_RIGHTS))
async def test_fund_rights_trip_every_permission_gate(name: str) -> None:
    permissions = (await key_info(load(name, now=NOW))).permissions
    with pytest.raises(WithdrawPermissionError, match="key_withdraw_permission"):
        m13_reject_withdraw(permissions)
    with pytest.raises(WithdrawPermissionRejected, match="key_withdraw_permission"):
        require_allow_listed(permissions)
    with pytest.raises(WithdrawPermissionRejected, match="key_withdraw_permission"):
        m2_reject_withdraw(permissions)


@pytest.mark.parametrize("name", sorted(OUTSIDE_ALLOW_LIST))
async def test_rights_outside_the_allow_list_trip_only_the_allow_list(name: str) -> None:
    permissions = (await key_info(load(name, now=NOW))).permissions
    with pytest.raises(WithdrawPermissionRejected, match="key_withdraw_permission"):
        require_allow_listed(permissions)
    m13_reject_withdraw(permissions)
    m2_reject_withdraw(permissions)


@pytest.mark.parametrize("name", ["compliant", "missing_trade_scope"])
async def test_trade_only_rights_pass_every_gate(name: str) -> None:
    """`missing_trade_scope` passes the gates: the required-scope check is the pipeline's."""
    permissions = (await key_info(load(name, now=NOW))).permissions
    require_allow_listed(permissions)
    m13_reject_withdraw(permissions)
    m2_reject_withdraw(permissions)


async def test_clock_skew_runs_the_exchange_clock_six_seconds_ahead() -> None:
    scenario = load("clock_skew", now=NOW)
    server = ServerTime.from_response(await call(scenario, "GET", "/v5/market/time"))
    assert server.time_us // 1000 - NOW_MS == 6000
    log: list[httpx.Request] = []
    with pytest.raises(ClockDriftError):
        await call(scenario, "GET", PROBE_PATH, log=log)
    assert len(log) == 2  # the adapter re-signs once after a 10002, then gives up
    assert scenario.reply("GET", PROBE_PATH).body["time"] == NOW_MS + 6000


def test_exactly_the_listed_replies_are_flagged_unconfirmed() -> None:
    flagged = {
        (name, stubbed)
        for name in sorted(PLAN_SCENARIOS)
        for stubbed, stub in manifest(name).get("rest", {}).items()
        if stub.get("code_unconfirmed")
    }
    assert flagged == UNCONFIRMED
    for name, stubbed in UNCONFIRMED:
        method, path = stubbed.split(" ", 1)
        scenario = _with(name) if name in OVERLAYS else load(name, now=NOW)
        assert scenario.reply(method, path).code_unconfirmed is True


@pytest.mark.parametrize(
    ("scenario", "method", "path", "endpoint"),
    [
        ("close_rejected", "POST", "/v5/order/create", EndpointClass.ORDER),
        (
            "leverage_refused_open_position",
            "POST",
            "/v5/position/set-leverage",
            EndpointClass.POSITION,
        ),
    ],
)
async def test_unconfirmed_refusals_are_business_rejections(
    scenario: str, method: str, path: str, endpoint: EndpointClass
) -> None:
    """Compared with the scenario's own code, never a literal (test plan section 9.3)."""
    loaded = load(scenario, now=NOW)
    sent = loaded.reply(method, path).body["retCode"]
    with pytest.raises(ExchangeError) as caught:
        await call(loaded, method, path, endpoint=endpoint, body=ORDER_BODY)
    assert (caught.value.exchange_ret_code, caught.value.retryable) == (sent, False)
    assert refusal(caught.value) is None  # a business rejection, never a verdict about the key


@pytest.mark.parametrize(("method", "path", "endpoint"), MODE_SWITCHES)
@pytest.mark.parametrize("overlay", ["open_position_btcusdt_5x_sl", "working_orders_2"])
async def test_overlay_mode_switch_refusals_are_plain_rejections(
    overlay: str, method: str, path: str, endpoint: EndpointClass
) -> None:
    """A code outside section 8.6's table, so its last row (a plain reject, not retried) applies,
    never 110025's hard error: mapping.py's catch-all, sent once, never a verdict about the key.
    The catch-all marks it retryable where section 8.6 says no (README, an E08 gap): pinned, so
    the day mapping.py follows the table this fails and the README line changes with it."""
    loaded = _with(overlay)
    sent = loaded.reply(method, path).body["retCode"]
    log: list[httpx.Request] = []
    with pytest.raises(UnknownStateError) as caught:
        await call(loaded, method, path, endpoint=endpoint, body=ORDER_BODY, log=log)
    assert (caught.value.exchange_ret_code, len(log)) == (sent, 1)
    assert caught.value.retryable is True
    assert refusal(caught.value) is None


def test_the_overlays_refuse_mode_switches_for_their_own_reasons() -> None:
    """Test plan section 9.3: an open-position refusal (TC-420), an active-order one (TC-421)."""
    position, orders = _with("open_position_btcusdt_5x_sl"), _with("working_orders_2")
    for method, path, _ in MODE_SWITCHES:
        mine, theirs = position.reply(method, path).body, orders.reply(method, path).body
        assert mine["retCode"] != theirs["retCode"]
        assert mine["retMsg"] != theirs["retMsg"]
        # One message serves all three calls of an overlay, so it names no single mode.
        assert not any("position mode" in body["retMsg"].lower() for body in (mine, theirs))


async def test_new_key_differs_from_compliant_only_in_its_creation_time() -> None:
    """No restriction reply is invented (C-13.5): demo orders go through (plan E27-TC-130)."""
    new, base = load("new_key_48h", now=NOW), load("compliant", now=NOW)
    assert new.stubbed_calls() == base.stubbed_calls()
    for stubbed in sorted(base.stubbed_calls()):
        method, path = stubbed.split(" ", 1)
        mine, theirs = new.reply(method, path), base.reply(method, path)
        if path == KEY_INFO_PATH:
            assert mine.body["result"].pop("createdAt") == "2026-10-16T07:00:00Z"
            theirs.body["result"].pop("createdAt")
        assert mine == theirs
    ack = await call(new, "POST", "/v5/order/create", endpoint=EndpointClass.ORDER, body=ORDER_BODY)
    assert ack["retCode"] == 0


def test_compliant_key_was_created_30_days_and_expires_365_days_from_now() -> None:
    result = load("compliant", now=NOW).reply("GET", KEY_INFO_PATH).body["result"]
    assert (result["createdAt"], result["expiredAt"]) == (
        "2026-09-16T09:00:00Z",
        "2027-10-16T09:00:00Z",
    )
    new_key = load("new_key_48h", now=NOW).reply("GET", KEY_INFO_PATH).body["result"]
    assert new_key["createdAt"] == "2026-10-16T07:00:00Z"


def test_key_info_pins_both_uta_flags_as_plan_dc_33() -> None:
    """Test plan section 10 DC-33: every key-info reply answers `unified: 0`, with `uta: 1`
    except `non_uta` (both 0), so the verdict rests on `uta` alone. The adapter reads `uta`
    (`compliant` passes, `non_uta` fails `key_not_unified`: `PIPELINE`); a build that read the
    deprecated `unified` would refuse `compliant`, which the plan files against DC-33."""
    answered = sorted(n for n, info in KEY_INFO.items() if isinstance(info, ApiKeyFacts))
    flags: dict[str, tuple[object, object]] = {}
    for name in answered:
        result = load(name, now=NOW).reply("GET", KEY_INFO_PATH).body["result"]
        flags[name] = (result["unified"], result["uta"])
    assert {"compliant", "non_uta"} <= set(flags)
    assert flags.pop("non_uta") == (0, 0)
    assert set(flags.values()) == {(0, 1)}


@pytest.mark.parametrize(
    ("name", "days"),
    [("compliant", 365), ("expiring_13d", 13), ("expiring_15d", 15), ("expired_key", 0)],
)
def test_deadline_day_follows_the_anchored_expiry(name: str, days: int) -> None:
    assert load(name, now=NOW).reply("GET", KEY_INFO_PATH).body["result"]["deadlineDay"] == days


def test_a_key_without_expiry_reports_no_deadline_day() -> None:
    scenario = load("compliant", now=NOW)
    no_expiry = dataclasses.replace(
        scenario, clock=dataclasses.replace(scenario.clock, key_expires_offset_ms=None)
    )
    result = no_expiry.reply("GET", KEY_INFO_PATH).body["result"]
    assert result["expiredAt"] == ""
    assert "deadlineDay" not in result


@pytest.mark.parametrize("name", KEY_SCENARIOS)
def test_every_key_scenario_echoes_the_rfc_5737_egress(name: str) -> None:
    assert load(name, now=NOW).egress_ip == EGRESS_IP


@pytest.mark.parametrize(
    ("method", "path", "endpoint"),
    [
        ("GET", "/v5/account/fee-rate", EndpointClass.ACCOUNT),
        ("POST", "/v5/position/set-leverage", EndpointClass.POSITION),
        ("POST", "/v5/position/trading-stop", EndpointClass.POSITION),
        ("POST", "/v5/order/create", EndpointClass.ORDER),
        ("POST", "/v5/order/cancel", EndpointClass.ORDER),
        ("GET", "/v5/order/realtime", EndpointClass.ORDER),
        ("GET", "/v5/position/list", EndpointClass.POSITION),
        *MODE_SWITCHES,
    ],
)
@pytest.mark.parametrize("name", ["compliant", "leverage_ok"])
async def test_compliant_trading_calls_succeed(
    name: str, method: str, path: str, endpoint: EndpointClass
) -> None:
    reply = await call(load(name, now=NOW), method, path, endpoint=endpoint, body=ORDER_BODY)
    assert reply["time"] == NOW_MS


async def test_fee_rate_carries_maker_and_taker_rates() -> None:
    reply = await call(load("compliant", now=NOW), "GET", "/v5/account/fee-rate")
    assert reply["result"]["list"] == [
        {"symbol": "BTCUSDT", "takerFeeRate": "0.00055", "makerFeeRate": "0.0002"}
    ]


@pytest.mark.parametrize("path", ["/v5/user/delete-api", "/v5/user/delete-sub-api"])
async def test_key_delete_answers_a_transport_error(path: str) -> None:
    with pytest.raises(TransportError):
        await call(load("key_delete_5xx", now=NOW), "POST", path, body={})


def test_rate_limit_reply_carries_the_documented_headers() -> None:
    reply = load("rate_limited_10018", now=NOW).reply("GET", KEY_INFO_PATH)
    assert reply.headers == {
        "X-Bapi-Limit": "10",
        "X-Bapi-Limit-Status": "0",
        "X-Bapi-Limit-Reset-Timestamp": str(NOW_MS + 600_000),
    }


@pytest.mark.parametrize(
    ("at_ms", "fails"),
    [(0, False), (9_999, False), (10_000, True), (29_999, True), (30_000, False)],
)
async def test_the_blip_fails_rest_for_twenty_seconds_only(at_ms: int, fails: bool) -> None:
    scenario = load("ws_blip_20s", now=NOW)
    if fails:
        with pytest.raises(TransportError):
            await call(scenario, "GET", PROBE_PATH, at_ms=at_ms)
    else:
        assert (await call(scenario, "GET", PROBE_PATH, at_ms=at_ms))["time"] == NOW_MS


def test_a_blip_switched_in_later_counts_from_the_switch() -> None:
    """TC-411's T0 is the switch (test plan section 9.3), so the scenario is loaded at it: the
    window runs 10 s to 30 s after the switch, and the replies carry the switch-time clock."""
    switch = NOW + timedelta(hours=1)
    blip = load("ws_blip_20s", now=switch)
    statuses = [blip.reply("GET", PROBE_PATH, at_ms=at).status for at in (9_999, 10_000, 30_000)]
    assert statuses == [200, 503, 200]
    assert blip.reply("GET", PROBE_PATH, at_ms=30_000).body["time"] == NOW_MS + 3_600_000


def test_compliant_ws_authenticates_then_streams_the_probe_wallet() -> None:
    ws = load("compliant", now=NOW).ws
    assert (ws.on_connect, ws.on_auth.do, ws.on_ping.do, ws.on_subscribe.do) == (
        "accept", "reply", "reply", "reply",
    )  # fmt: skip
    assert ws.on_auth.frame == {"success": True, "op": "auth"}
    assert ws.on_subscribe.frame == {"success": True, "op": "subscribe"}
    assert ws.on_ping.frame == {"op": "pong"}
    assert [(s.after_ms, s.every_ms) for s in ws.after_auth] == [(0, None), (5000, 5000)]
    wallet = load("compliant", now=NOW).reply("GET", PROBE_PATH).body["result"]["list"]
    assert all(s.frame == {"topic": "wallet", "data": wallet} for s in ws.after_auth)
    assert ws.timeline == ()


@pytest.mark.parametrize(
    ("name", "connect", "auth", "sends", "timeline"),
    [
        ("demo_ws_unreachable", "refuse", "reply", 2, []),
        ("ws_auth_timeout", "accept", "ignore", 2, []),
        ("live_key_on_demo", "accept", "close", 2, []),
        ("unknown_key", "accept", "close", 2, []),
        ("ws_quiet", "accept", "reply", 1, []),
        ("ws_quiet_rest_fail", "accept", "reply", 1, []),
        ("ws_auth_then_drop", "accept", "reply", 1, [(5000, "refuse_reconnects"), (5000, "drop")]),
        ("ws_drop_rest_fail", "accept", "reply", 1, [(5000, "refuse_reconnects"), (5000, "drop")]),
        (
            "ws_blip_20s",
            "accept",
            "reply",
            2,
            [(10000, "refuse_reconnects"), (10000, "drop"), (30000, "accept_reconnects")],
        ),
    ],
)
def test_ws_script(
    name: str, connect: str, auth: str, sends: int, timeline: list[tuple[int, str]]
) -> None:
    ws = load(name, now=NOW).ws
    assert (ws.on_connect, ws.on_auth.do, len(ws.after_auth)) == (connect, auth, sends)
    assert [(s.at_ms, s.do) for s in ws.timeline] == timeline
    assert ws.on_ping.do == "reply"


@pytest.mark.parametrize("name", ROTATIONS)
async def test_rotation_pair_resolves_two_distinct_keys(name: str) -> None:
    pair = load_rotation(name, now=NOW)
    assert pair.old.name == "compliant"
    assert pair.old.key_id != pair.new.key_id
    assert (await key_info(pair.new)).uid == pair.old.account_uid
    new_rights = (await key_info(pair.new)).permissions
    if name == "rotation_ok":
        require_allow_listed(new_rights)
    else:
        with pytest.raises(WithdrawPermissionRejected):
            require_allow_listed(new_rights)


async def test_the_position_overlay_seeds_one_5x_btcusdt_position_with_its_native_sl() -> None:
    scenario = _with("open_position_btcusdt_5x_sl")
    reply = await call(scenario, "GET", "/v5/position/list", endpoint=EndpointClass.POSITION)
    [position] = reply["result"]["list"]
    assert (position["symbol"], position["side"], position["leverage"]) == ("BTCUSDT", "Buy", "5")
    # A long's native stop-loss sits below its entry (C-2.6); prices compare as Decimal.
    assert Decimal(position["stopLoss"]) < Decimal(position["avgPrice"])
    assert reply["time"] == NOW_MS
    closing = await call(
        scenario, "POST", "/v5/order/create", endpoint=EndpointClass.ORDER, body=ORDER_BODY
    )
    assert closing["retCode"] == 0  # accepted; the fill itself is #2893's state


async def test_the_order_overlay_seeds_two_resting_limit_orders_that_cancel() -> None:
    scenario = _with("working_orders_2")
    orders = await call(scenario, "GET", "/v5/order/realtime", endpoint=EndpointClass.ORDER)
    listed = orders["result"]["list"]
    assert [(o["symbol"], o["orderType"], o["orderStatus"]) for o in listed] == [
        ("BTCUSDT", "Limit", "New"),
        ("BTCUSDT", "Limit", "New"),
    ]
    assert len({o["orderLinkId"] for o in listed}) == 2
    cancel = await call(
        scenario, "POST", "/v5/order/cancel", endpoint=EndpointClass.ORDER, body=ORDER_BODY
    )
    assert cancel["retCode"] == 0


async def test_the_history_overlay_seeds_a_flat_round_trip() -> None:
    scenario = _with("history_round_trip")
    orders = await call(scenario, "GET", "/v5/order/history", endpoint=EndpointClass.ORDER)
    fills = await call(scenario, "GET", "/v5/execution/list", endpoint=EndpointClass.ORDER)
    positions = await call(scenario, "GET", "/v5/position/list", endpoint=EndpointClass.POSITION)
    assert [(o["side"], o["orderType"], o["orderStatus"]) for o in orders["result"]["list"]] == [
        ("Buy", "Market", "Filled"),
        ("Sell", "Market", "Filled"),
    ]
    assert [f["orderLinkId"] for f in fills["result"]["list"]] == [
        o["orderLinkId"] for o in orders["result"]["list"]
    ]
    assert positions["result"]["list"] == []


async def test_an_overlay_replaces_the_compliant_default() -> None:
    plain, seeded = load("compliant", now=NOW), _with("open_position_btcusdt_5x_sl")
    assert plain.reply("GET", "/v5/position/list").body["result"]["list"] == []
    assert seeded.reply("POST", "/v5/position/switch-mode").body["retCode"] != 0
    assert plain.reply("POST", "/v5/position/switch-mode").body["retCode"] == 0


async def test_a_scenario_fault_beats_an_overlay() -> None:
    """README lookup order: a fault the scenario sets wins over seeded state (TC-305, TC-410)."""
    rejected = _with("open_position_btcusdt_5x_sl", "close_rejected")
    assert rejected.reply("POST", "/v5/order/create").code_unconfirmed is True
    assert rejected.reply("GET", "/v5/position/list").body["result"]["list"] != []
    with pytest.raises(TransportError):
        await call(
            _with("open_position_btcusdt_5x_sl", "ws_drop_rest_fail"),
            "GET",
            "/v5/position/list",
            endpoint=EndpointClass.POSITION,
        )


def test_overlays_combine_in_the_order_named_and_reach_both_rotated_keys() -> None:
    both = load("compliant", now=NOW, overlays=["open_position_btcusdt_5x_sl", "working_orders_2"])
    assert len(both.reply("GET", "/v5/position/list").body["result"]["list"]) == 1
    assert len(both.reply("GET", "/v5/order/realtime").body["result"]["list"]) == 2
    pair = load_rotation("rotation_ok", now=NOW, overlays=["working_orders_2"])
    for key in (pair.old, pair.new):
        assert len(key.reply("GET", "/v5/order/realtime").body["result"]["list"]) == 2


def test_every_stubbed_path_passes_the_rest_path_guard() -> None:
    calls = {c for n in sorted(PLAN_SCENARIOS) for c in manifest(n).get("rest", {})} - {WILDCARD}
    assert calls  # the guard check below must not pass vacuously
    for stubbed in calls:
        assert validate_rest_path(stubbed.split(" ", 1)[1])


def test_no_pack_file_holds_a_typed_secret() -> None:
    secrets = [load(n, now=NOW).typed_secret() for n in KEY_SCENARIOS]
    for path in PACK_ROOT.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert not any(s in text for s in secrets), path.name


def test_unstubbed_calls_fail_loudly() -> None:
    with pytest.raises(UnstubbedCall, match="nothing answers GET /v5/position/closed-pnl"):
        load("compliant", now=NOW).reply("GET", "/v5/position/closed-pnl")


@pytest.mark.parametrize(
    ("loader", "message"),
    [
        (lambda: load("compliant", now=datetime(2026, 10, 16, 9, 0)), "timezone-aware"),
        (lambda: load("rotation_ok", now=NOW), "rotation pair"),
        (lambda: load_rotation("compliant", now=NOW), "not a rotation pair"),
        (lambda: load("working_orders_2", now=NOW), "is an overlay"),
        (lambda: load("compliant", now=NOW, overlays=["ip_missing"]), "not an overlay"),
        (lambda: load("compliant", now=NOW, switched=True), "no runtime switch"),
    ],
    ids=[
        "naive_now",
        "rotation_pair_via_load",
        "key_scenario_via_load_rotation",
        "overlay_via_load",
        "key_scenario_as_overlay",
        "switch_without_switch_to",
    ],
)
def test_loader_refuses_misuse(loader: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        loader()


def test_loader_refuses_an_unknown_scenario() -> None:
    with pytest.raises(KeyError):
        load("no_such_scenario", now=NOW)


def test_merge_patch_follows_rfc_7396() -> None:
    target = {"a": {"b": "c", "keep": 1}, "drop": 1}
    assert merge_patch(target, {"a": {"b": "d"}, "drop": None}) == {"a": {"b": "d", "keep": 1}}
    assert merge_patch(target, ["x"]) == ["x"]
    assert target == {"a": {"b": "c", "keep": 1}, "drop": 1}


@pytest.mark.parametrize(
    ("name", "account_uid", "kind"),
    [
        ("compliant", None, (90000001, True, "0")),
        ("key_delete_5xx", None, (90000011, False, "90000001")),
        ("close_rejected", None, (90000011, False, "90000001")),
        ("compliant", "90000011", (90000011, False, "90000001")),
        ("compliant", "90000012", (90000012, False, "90000001")),
    ],
)
def test_key_info_reports_the_account_kind(
    name: str, account_uid: str | None, kind: tuple[int, bool, str]
) -> None:
    scenario = load(name, now=NOW, account_uid=account_uid)
    result = scenario.reply("GET", KEY_INFO_PATH).body["result"]
    assert (result["userID"], result["isMaster"], result["parentUid"]) == kind


def test_loader_refuses_an_account_outside_section_9_2() -> None:
    with pytest.raises(ValueError, match=r"not a section 9\.2 account"):
        load("compliant", now=NOW, account_uid="90000099")


def test_payloads_never_leave_the_pack_and_the_shared_corpus() -> None:
    """Defence in depth behind the schema's path pattern (the JS checks plant the same)."""
    with pytest.raises(ValueError, match="outside the fixtures package"):
        _payload("../../../services/api/pyproject.toml")
    assert _payload("../bybit/2026-10-05/rest/server_time.json")["retCode"] == 0


def test_account_uid_override_reaches_key_info() -> None:
    body = load("compliant", now=NOW, account_uid="90000012").reply("GET", KEY_INFO_PATH).body
    assert body["result"]["userID"] == 90000012
    pinned = load("uid_mismatch", now=NOW, account_uid="90000012").reply("GET", KEY_INFO_PATH)
    assert pinned.body["result"]["userID"] == 90000099
