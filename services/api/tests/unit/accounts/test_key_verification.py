"""E27-T03 verification pipeline (#836): the seven checks, their order and the refusal classes.

Facts come from the documented-shape fixtures (`tests/fixtures/key_verification/`) through the
adapter parsers, and scenarios are fixture edits, so every case runs on the shape production sees.
`Sources` stands in for slice 2's wiring: it maps an adapter error to `KeyRefused` or
`VerificationInconclusive` with `key_info.refusal`, and records the order of signed calls.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts.models import AccountKind, ExchangeAccount, ExchangeEnv
from candleviewer.accounts.verification import (
    KeyRefused,
    Refusal,
    Rule,
    VerificationFailure,
    VerificationInconclusive,
    VerificationPolicy,
    VerificationResult,
    VerificationWarning,
    verify,
)
from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.bybit.key_info import (
    VERDICT_REASONS,
    ApiKeyFacts,
    ProbeFacts,
    refusal,
)
from candleviewer.exchange.bybit.mapping import map_ret_code
from tests._corpus import rest
from tests.unit.accounts._helpers import EGRESS, NOW, WITHDRAW, T, facts, load, probed
from tests.unit.accounts._permission_cases import BASE, KNOWN_GAPS, REFUSED, non_json_cases

#: Stand-in key id and secret in a reply; the dummy prefix is the gitleaks allow-list's (SR-145).
MARKER = "DUMMYKEY_NOT_A_KEY_0001"
POLICY = VerificationPolicy(egress_ip=EGRESS)
ACCOUNT = ExchangeAccount(
    id=UUID(int=1),
    env=ExchangeEnv.DEMO,
    kind=AccountKind.MAIN,
    exchange_uid="1000001",
    label="fx-demo",
    created_at=NOW,
    updated_at=NOW,
)


def error(body: dict[str, Any]) -> ExchangeError:
    return map_ret_code(int(body["retCode"]), str(body["retMsg"]))


class Sources:
    def __init__(self, key: object, probe: object) -> None:
        self.key, self.seen = key, probe
        self.calls: list[str] = []

    @staticmethod
    def _raise(outcome: object) -> None:
        if isinstance(outcome, ExchangeError):
            verdict = refusal(outcome)
            if verdict is None:
                raise VerificationInconclusive(type(outcome).__name__)
            raise KeyRefused(Refusal(verdict[0]), verdict[1])

    async def key_info(self) -> ApiKeyFacts:
        self.calls.append("key_info")
        self._raise(self.key)
        assert isinstance(self.key, ApiKeyFacts)
        return self.key

    async def probe(self) -> ProbeFacts:
        self.calls.append("probe")
        self._raise(self.seen)
        assert isinstance(self.seen, ProbeFacts)
        return self.seen


async def run(
    key: object = None, probe: object = None, *, read_only: bool = False, **policy: Any
) -> tuple[VerificationResult, list[str]]:
    src = Sources(facts() if key is None else key, probed() if probe is None else probe)
    result = await verify(
        ACCOUNT,
        read_only=read_only,
        key_info=src.key_info,
        probe=src.probe,
        policy=dataclasses.replace(POLICY, **policy),
        now=NOW,
    )
    return result, src.calls


def rules(result: VerificationResult) -> list[Rule]:
    return [f.rule for f in result.failures]


#: Key-info refusals with a verdict, by exchange code.
REFUSALS: dict[int, ExchangeError] = {
    10003: error(load("error_10003.json")),
    10005: map_ret_code(10005, "permission denied"),
    10010: error(load("error_10010.json")),
    33004: error(load("error_33004.json")),
}


def test_adapter_verdicts_and_refusal_members_correspond_one_to_one() -> None:
    assert {Refusal(reason) for reason in VERDICT_REASONS} == set(Refusal)


async def test_compliant_trade_key_passes_with_its_facts() -> None:
    result, _ = await run()
    assert result == VerificationResult(
        passed=True,
        uid="1000001",
        unified=True,
        permissions={
            **dict.fromkeys(facts().permissions, ()),
            "ContractTrade": ("Order", "Position"),
            "Derivatives": ("DerivativesTrade",),
        },
        ip_whitelist=(EGRESS,),
        ip_whitelist_matches_egress=True,
        clock_offset_ms=0,
        key_info_ret_code=0,
        probe_ret_code=0,
        can_trade=True,
        expires_at=datetime(2027, 4, 13, tzinfo=UTC),
    )


async def test_compliant_trade_key_reads_key_info_before_the_probe() -> None:
    _, calls = await run()
    assert calls == ["key_info", "probe"]


@pytest.mark.parametrize(
    ("key", "read_only"),
    [
        pytest.param(facts(permissions=WITHDRAW), False, id="fund_right"),
        pytest.param(facts(permissions={**BASE, "ContractTrade": []}), False, id="scopes"),
        pytest.param(facts(), True, id="read_only_declared_with_write_access"),
        pytest.param(facts(uta=0), False, id="not_unified"),
        pytest.param(facts(userID=999), False, id="foreign_uid"),
        pytest.param(facts(ips=[]), False, id="whitelist_missing"),
        pytest.param(facts(ips=["198.51.100.1"]), False, id="whitelist_mismatch"),
        pytest.param(facts(expiredAt=NOW.isoformat()), False, id="expired"),
        pytest.param(REFUSALS[10003], False, id="key_info_refused"),
    ],
)
async def test_blocking_failure_never_reaches_the_signed_probe(
    key: object, read_only: bool
) -> None:
    _, calls = await run(key, read_only=read_only)
    assert calls == ["key_info"]


async def test_withdraw_right_fails_the_gate_with_the_contract_message() -> None:
    result, _ = await run(facts(permissions=WITHDRAW))
    message = "permissions.Wallet contains 'Withdraw'"
    assert result.failures == (VerificationFailure(Rule.WITHDRAW_PERMISSION, message),)


async def test_withdraw_right_is_reported_as_withdraw_enabled() -> None:
    result, _ = await run(facts(permissions=WITHDRAW))
    assert (result.passed, result.withdraw_enabled) == (False, True)


_GATE_CASES: list[tuple[str, Any]] = [(c[0], c[1]) for c in REFUSED + KNOWN_GAPS]
_GATE_CASES += [
    *non_json_cases(),
    ("spot_right", {**BASE, "Spot": ["SpotTrade"]}),
    ("extra_contract_right", {**BASE, "ContractTrade": ["Order", "Position", "Xfer"]}),
    ("fund_group_other_name", {**BASE, "FiatP2P": ["FiatP2POrder"]}),
    ("scalar_right", {**BASE, "Affiliate": [1]}),
    ("allowed_group_as_object", {**BASE, "ContractTrade": {"Order": [], "Position": []}}),
    ("non_text_group_granting_nothing", {**BASE, b"Wallet": []}),
]


@pytest.mark.parametrize(
    "permissions", [c[1] for c in _GATE_CASES], ids=[c[0] for c in _GATE_CASES]
)
async def test_every_refused_or_unlisted_right_fails_the_gate(permissions: Any) -> None:
    result, _ = await run(dataclasses.replace(facts(), permissions=permissions))
    verdict = (result.passed, result.withdraw_enabled, set(rules(result)))
    assert verdict == (False, True, {Rule.WITHDRAW_PERMISSION})


LOOKALIKE_RIGHT = {**BASE, "Wallet": ["With\u200bdraw"]}
SPACED_GROUP = {**BASE, "Wal let": ["Order"]}


@pytest.mark.parametrize(
    ("permissions", "message"),
    [
        (LOOKALIKE_RIGHT, "permissions.Wallet holds a right outside the allowed set"),
        (SPACED_GROUP, "permissions hold a group outside the allowed set"),
    ],
    ids=["right", "group"],
)
async def test_non_canonical_names_get_a_template_message(permissions: Any, message: str) -> None:
    result, _ = await run(dataclasses.replace(facts(), permissions=permissions))
    assert result.failures == (VerificationFailure(Rule.WITHDRAW_PERMISSION, message),)


@pytest.mark.parametrize("permissions", [LOOKALIKE_RIGHT, SPACED_GROUP], ids=["right", "group"])
async def test_non_canonical_names_are_left_out_of_the_display(permissions: Any) -> None:
    result, _ = await run(dataclasses.replace(facts(), permissions=permissions))
    assert result.permissions == {group: tuple(rights) for group, rights in BASE.items()}


@pytest.mark.parametrize("empty", [[], None, ""])
async def test_groups_that_grant_nothing_pass_the_gate(empty: Any) -> None:
    result, _ = await run(facts(permissions={**BASE, "Wallet": empty, "Withdraw": []}))
    assert (result.passed, result.withdraw_enabled) == (True, False)


@pytest.mark.parametrize(
    ("declared", "flag", "contract", "message"),
    [
        (False, 0, ["Order"], "permissions.ContractTrade lacks 'Position'"),
        (False, 0, [], "permissions.ContractTrade lacks 'Order', 'Position'"),
        (False, 1, ["Order", "Position"], "the key is read-only; a trade key needs write access"),
        (True, 0, [], "a read-only key has write access"),
    ],
)
async def test_scope_or_write_access_mismatch_fails_check_three(
    declared: bool, flag: int, contract: list[str], message: str
) -> None:
    key = facts(readOnly=flag, permissions={**BASE, "ContractTrade": contract})
    result, _ = await run(key, read_only=declared)
    assert result.failures == (VerificationFailure(Rule.MISSING_SCOPES, message),)


@pytest.mark.parametrize("contract", [[], ["Order", "Position"]])
async def test_read_only_key_passes_without_trade_access(contract: list[str]) -> None:
    key = facts(readOnly=1, permissions={**BASE, "ContractTrade": contract})
    result, _ = await run(key, read_only=True)
    assert (result.passed, result.read_only, result.can_trade) == (True, True, False)


async def test_non_uta_key_fails_check_four() -> None:
    result, _ = await run(facts(uta=0))
    message = "the account is not a unified trading account"
    assert result.failures == (VerificationFailure(Rule.NOT_UNIFIED, message),)


async def test_foreign_uid_fails_check_four_naming_the_account_uid() -> None:
    result, _ = await run(facts(userID=999))
    message = "the key belongs to another UID, not 1000001"
    assert result.failures == (VerificationFailure(Rule.UID_MISMATCH, message),)


async def test_non_uta_and_foreign_uid_both_fail_in_check_order() -> None:
    result, _ = await run(facts(uta=0, userID=999))
    assert rules(result) == [Rule.NOT_UNIFIED, Rule.UID_MISMATCH]


def ip_missing(where: str) -> VerificationFailure:
    text = f"the key has no IP whitelist; {where} in the exchange's key settings"
    return VerificationFailure(Rule.IP_WHITELIST_MISSING, text)


def ip_mismatch(text: str) -> VerificationFailure:
    return VerificationFailure(Rule.IP_WHITELIST_MISMATCH, text)


ONLY_EGRESS = ip_mismatch(f"the IP whitelist must hold only the egress IP {EGRESS}")
NO_EGRESS = ip_mismatch("the egress IP is not configured")


@pytest.mark.parametrize(
    ("ips", "egress", "failure"),
    [
        ([], EGRESS, ip_missing(f"add {EGRESS}")),
        (["*"], EGRESS, ip_missing(f"add {EGRESS}")),
        (["*"], None, ip_missing("set the egress IP and add it")),
        ([EGRESS, "198.51.100.1"], EGRESS, ONLY_EGRESS),
        (["203.0.113.0/24"], EGRESS, ONLY_EGRESS),
        (["198.51.100.1"], EGRESS, ONLY_EGRESS),
        (["not-an-ip"], EGRESS, ONLY_EGRESS),
        ([EGRESS], None, NO_EGRESS),
        ([EGRESS], "203.0.113.0/24", NO_EGRESS),
        (
            ["203.0.113.0/24"],
            "203.0.113.0",
            ip_mismatch("the IP whitelist must hold only the egress IP 203.0.113.0"),
        ),
    ],
)
async def test_whitelist_other_than_the_egress_ip_fails_check_five(
    ips: list[str], egress: str | None, failure: VerificationFailure
) -> None:
    result, _ = await run(facts(ips=ips), egress_ip=egress)
    assert (result.failures, result.ip_whitelist_matches_egress) == ((failure,), False)


@pytest.mark.parametrize("entry", [EGRESS, f"{EGRESS}/32", f"::ffff:{EGRESS}"])
async def test_whitelist_of_only_the_egress_host_passes(entry: str) -> None:
    result, _ = await run(facts(ips=[entry]))
    assert (result.passed, result.ip_whitelist_matches_egress) == (True, True)


@pytest.mark.parametrize(
    ("ips", "shown"),
    [(["*"], ("*",)), (["not-an-ip"], ()), ([EGRESS, "not-an-ip"], (EGRESS,))],
)
async def test_whitelist_display_keeps_addresses_and_the_wildcard_only(
    ips: list[str], shown: tuple[str, ...]
) -> None:
    result, _ = await run(facts(ips=ips))
    assert result.ip_whitelist == shown


@pytest.mark.parametrize(
    ("ahead", "warnings"),
    [
        (timedelta(seconds=1), (VerificationWarning.KEY_EXPIRES_SOON,)),
        (timedelta(days=13), (VerificationWarning.KEY_EXPIRES_SOON,)),
        (timedelta(days=14), ()),
    ],
    ids=["1s", "13d", "14d"],
)
async def test_future_expiry_is_at_most_a_warning(
    ahead: timedelta, warnings: tuple[VerificationWarning, ...]
) -> None:
    result, _ = await run(facts(expiredAt=(NOW + ahead).isoformat()))
    assert (result.passed, result.warnings) == (True, warnings)


@pytest.mark.parametrize(
    "ago", [timedelta(0), timedelta(seconds=1), timedelta(days=30)], ids=["now", "1s", "30d"]
)
async def test_expiry_at_or_before_now_fails_check_six(ago: timedelta) -> None:
    result, _ = await run(facts(expiredAt=(NOW - ago).isoformat()))
    expired = VerificationFailure(Rule.KEY_EXPIRED, "the key has expired")
    assert (result.failures, result.warnings) == ((expired,), ())


def skewed(offset: int) -> ProbeFacts:
    """A 100 ms probe whose exchange clock is `offset` ms ahead of the host's midpoint."""
    return probed(sent=T - offset - 50, received=T - offset + 50)


@pytest.mark.parametrize("offset", [-12_000, 0, 501])
async def test_clock_offset_is_exchange_time_minus_the_host_midpoint(offset: int) -> None:
    result, _ = await run(probe=skewed(offset))
    assert result.clock_offset_ms == offset


@pytest.mark.parametrize(
    ("offset", "warnings"),
    [
        (-12_000, (VerificationWarning.CLOCK_OFFSET,)),
        (501, (VerificationWarning.CLOCK_OFFSET,)),
        (-501, (VerificationWarning.CLOCK_OFFSET,)),
        (500, ()),
        (-500, ()),
    ],
)
async def test_clock_offset_above_500_ms_is_a_warning_only(
    offset: int, warnings: tuple[VerificationWarning, ...]
) -> None:
    result, _ = await run(probe=skewed(offset))
    assert (result.passed, result.warnings) == (True, warnings)


@pytest.mark.parametrize(("window", "latency"), [(5000, 5000), (2000, 2000), (2000, 0)])
async def test_probe_inside_the_receive_window_passes(window: int, latency: int) -> None:
    result, _ = await run(probe=probed(sent=T, received=T + latency), recv_window_ms=window)
    assert (result.passed, result.probe_ret_code) == (True, 0)


@pytest.mark.parametrize(("window", "latency"), [(5000, 5001), (2000, 2001)])
async def test_accepted_probe_slower_than_the_receive_window_is_inconclusive(
    window: int, latency: int
) -> None:
    with pytest.raises(VerificationInconclusive, match="probe_slow"):
        await run(probe=probed(sent=T, received=T + latency), recv_window_ms=window)


@pytest.mark.parametrize(
    ("code", "failure"),
    [
        (
            10003,
            VerificationFailure(Rule.WRONG_ENVIRONMENT, "key does not belong to this environment"),
        ),
        (10005, VerificationFailure(Rule.MISSING_SCOPES, "the key lacks a required permission")),
        (
            10010,
            ip_mismatch(
                f"the exchange refused the egress IP {EGRESS}; add it to the key's IP whitelist"
            ),
        ),
        (33004, VerificationFailure(Rule.KEY_EXPIRED, "the exchange refused the key as expired")),
    ],
)
async def test_key_info_refusal_is_a_verdict_with_its_rule(
    code: int, failure: VerificationFailure
) -> None:
    result, _ = await run(REFUSALS[code])
    assert result.failures == (failure,)


@pytest.mark.parametrize("code", list(REFUSALS))
async def test_key_info_refusal_code_is_never_reported_as_a_probe_code(code: int) -> None:
    result, _ = await run(REFUSALS[code])
    assert (result.key_info_ret_code, result.probe_ret_code) == (code, None)


async def test_ip_refusal_without_a_configured_egress_ip_names_none() -> None:
    result, _ = await run(REFUSALS[10010], egress_ip=None)
    assert result.failures == (ip_mismatch("the exchange refused the egress IP"),)


async def test_probe_refusal_fails_check_seven_with_the_probe_code() -> None:
    result, _ = await run(probe=error(load("error_10003.json")))
    failure = VerificationFailure(Rule.PROBE_FAILED, "the exchange refused the signed probe")
    outcome = (result.failures, result.key_info_ret_code, result.probe_ret_code)
    assert outcome == ((failure,), 0, 10003)


INCONCLUSIVE = [error(load("error_10004.json")), error(rest("rest/error_10002.json"))]


@pytest.mark.parametrize("outcome", INCONCLUSIVE, ids=["signature", "clock"])
async def test_inconclusive_key_info_refusal_gives_no_verdict(outcome: ExchangeError) -> None:
    with pytest.raises(VerificationInconclusive):
        await run(outcome)


@pytest.mark.parametrize("outcome", INCONCLUSIVE, ids=["signature", "clock"])
async def test_inconclusive_probe_refusal_gives_no_verdict(outcome: ExchangeError) -> None:
    with pytest.raises(VerificationInconclusive):
        await run(probe=outcome)


async def test_host_clock_step_during_the_probe_is_inconclusive() -> None:
    with pytest.raises(VerificationInconclusive, match="probe_clock_step"):
        await run(probe=probed(sent=T + 10, received=T))


async def naive_run(src: Sources) -> VerificationResult:
    naive = NOW.replace(tzinfo=None)
    return await verify(
        ACCOUNT, read_only=False, key_info=src.key_info, probe=src.probe, policy=POLICY, now=naive
    )


async def test_naive_now_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await naive_run(Sources(facts(), probed()))


async def test_naive_now_makes_no_signed_call() -> None:
    src = Sources(facts(), probed())
    with pytest.raises(ValueError, match="timezone-aware"):
        await naive_run(src)
    assert src.calls == []


async def test_result_never_carries_the_reply_key_material() -> None:
    result, _ = await run(facts(apiKey=MARKER, secret=MARKER))
    assert MARKER not in repr(result)


def test_result_has_no_credential_field() -> None:
    assert {f.name for f in dataclasses.fields(VerificationResult)} == {
        "passed", "uid", "unified", "permissions", "withdraw_enabled", "ip_whitelist",
        "ip_whitelist_matches_egress", "clock_offset_ms", "key_info_ret_code", "probe_ret_code",
        "warnings", "failures", "read_only", "can_trade", "expires_at",
    }  # fmt: skip
