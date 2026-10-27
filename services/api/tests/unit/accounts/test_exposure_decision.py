"""The exposure read's decision, in `OpenExposure`'s order (E27-S04 B2a, #898; 22 `OpenExposure`).

Every branch of 22's decision table, a Hypothesis run against a reference model of its Order rule,
the take-profit-only stop-loss case (CR-03) and contract checks that tie the four word groups to
22's own text, so a new `KeyProbeError` value or a reworded branch fails here.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.accounts.exposure import (
    DEAD,
    EXCHANGE_ERROR,
    FIXABLE,
    PROBE_ERRORS,
    UNAVAILABLE,
    ExchangePosition,
    ExposureFailed,
    ExposureKnown,
    ExposureUnknown,
    KeyExposure,
    KeyReadFailed,
    combine,
    decide,
)
from candleviewer.api.contract_conformance import load_openapi_spec

K1, K2, K3 = UUID(int=1), UUID(int=2), UUID(int=3)
READ = KeyExposure((), 2)


def _position(**over: Any) -> ExchangePosition:
    fields: dict[str, Any] = {
        "symbol": "BTCUSDT", "position_idx": 0, "side": "long", "size": Decimal("1"),
        "avg_price": Decimal("60000"), "mark_price": None, "liq_price": None,
        "leverage": Decimal("5"), "unrealised_pnl": Decimal("0"), "take_profit": None,
        "stop_loss": None, "trailing_stop": None, "updated_at_us": 1,
    }  # fmt: skip
    return ExchangePosition(**(fields | over))


# -- the branches --


def test_decide_no_signable_key_dead_leave_positions() -> None:
    assert decide({}) == ExposureUnknown("leave_positions", ())


@pytest.mark.parametrize("word", sorted(PROBE_ERRORS))
def test_decide_one_key_read_wins_over_any_failure(word: str) -> None:
    got = decide({K1: KeyReadFailed(word, 10002), K2: READ})
    assert got == ExposureKnown(K2, (), 2)


@pytest.mark.parametrize("word", sorted(UNAVAILABLE))
def test_decide_no_answer_failed_read_503_without_code(word: str) -> None:
    got = decide({K1: KeyReadFailed(word, 10016)})
    assert got == ExposureFailed(503, word, None, ((K1, word),))


@pytest.mark.parametrize("word", sorted(EXCHANGE_ERROR))
def test_decide_answered_failed_read_502_with_its_code(word: str) -> None:
    assert decide({K1: KeyReadFailed(word, 10002)}) == ExposureFailed(
        502, word, 10002, ((K1, word),)
    )
    assert decide({K1: KeyReadFailed(word)}) == ExposureFailed(502, word, None, ((K1, word),))


def test_decide_keys_failing_both_ways_503() -> None:
    got = decide({K1: KeyReadFailed("clock_drift", 10002), K2: KeyReadFailed("transport_error")})
    errors = ((K1, "clock_drift"), (K2, "transport_error"))
    assert got == ExposureFailed(503, "transport_error", None, errors)


def test_decide_vault_refused_counts_with_503_group() -> None:
    got = decide({K1: KeyReadFailed("vault_refused"), K2: KeyReadFailed("rate_limited", 10006)})
    assert isinstance(got, ExposureFailed) and (got.status, got.probe_error) == (
        503,
        "vault_refused",
    )


def test_decide_failed_read_beats_every_refusal() -> None:
    got = decide({K1: KeyReadFailed("auth_error"), K2: KeyReadFailed("ip_not_allowed"),
                  K3: KeyReadFailed("exchange_unknown", 33004)})  # fmt: skip
    assert got == ExposureFailed(
        502, "exchange_unknown", 33004,
        ((K1, "auth_error"), (K2, "ip_not_allowed"), (K3, "exchange_unknown")),
    )  # fmt: skip


def test_decide_lowest_key_of_deciding_group_gives_code() -> None:
    got = decide({K3: KeyReadFailed("clock_drift", 10002), K2: KeyReadFailed("rate_limited", 10006),
                  K1: KeyReadFailed("auth_error")})  # fmt: skip
    assert isinstance(got, ExposureFailed) and (got.probe_error, got.ret_code) == (
        "rate_limited",
        10006,
    )
    assert [key for key, _ in got.key_errors] == [K1, K2, K3]


@pytest.mark.parametrize("word", sorted(FIXABLE))
def test_decide_fixable_refusal_next_to_dead_key_fix_key(word: str) -> None:
    got = decide({K1: KeyReadFailed("auth_error"), K2: KeyReadFailed(word)})
    assert got == ExposureUnknown("fix_key", ((K1, "auth_error"), (K2, word)))


def test_decide_every_key_auth_error_dead_with_each_word() -> None:
    got = decide({K2: KeyReadFailed("auth_error", 10003), K1: KeyReadFailed("auth_error", 10004)})
    assert got == ExposureUnknown("leave_positions", ((K1, "auth_error"), (K2, "auth_error")))


# -- one key's two calls --


def test_combine_failed_read_beats_refusal_on_one_key() -> None:
    picked = combine([KeyReadFailed("auth_error"), KeyReadFailed("timeout")])
    assert picked.probe_error == "timeout"


def test_combine_no_answer_beats_answered_error_and_fixable_beats_dead() -> None:
    no_answer = combine([KeyReadFailed("clock_drift", 10002), KeyReadFailed("vault_refused")])
    fixable = combine([KeyReadFailed("auth_error"), KeyReadFailed("permission_denied")])
    assert (no_answer.probe_error, fixable.probe_error) == ("vault_refused", "permission_denied")


def test_combine_nothing_refused() -> None:
    with pytest.raises(ValueError, match="no failure"):
        combine([])


def test_key_read_failed_word_outside_contract_refused() -> None:
    with pytest.raises(ValueError, match="KeyProbeError"):
        KeyReadFailed("exchange text")


# -- the native stop-loss (CR-03) --


@pytest.mark.parametrize(
    ("over", "present"),
    [
        ({"stop_loss": Decimal("58000")}, True),
        ({"take_profit": Decimal("65000")}, False),
        ({"stop_loss": Decimal("58000"), "take_profit": Decimal("65000")}, True),
        ({}, False),
        ({"trailing_stop": Decimal("500")}, False),
    ],
    ids=["stop_loss_only", "take_profit_only", "both", "neither", "trailing_only"],
)
def test_native_stop_present_only_stop_loss_counts(over: dict[str, Any], present: bool) -> None:
    assert _position(**over).native_stop_present is present


# -- a reference model of 22's Order rule --

_OUTCOME = st.one_of(
    st.just(READ),
    st.builds(
        KeyReadFailed, st.sampled_from(sorted(PROBE_ERRORS)), st.none() | st.integers(1, 99_999)
    ),
)


_NO_ANSWER = {"timeout", "transport_error", "vault_refused"}
_ANSWERED = {"clock_drift", "rate_limited", "service_unavailable", "exchange_unknown"}


def _model(outcomes: dict[UUID, KeyExposure | KeyReadFailed]) -> tuple[Any, ...]:
    """22's Order, written from its text: (1) a read, (2) a failed read, (3) fixable, (4) dead."""
    reads = [key for key, got in outcomes.items() if isinstance(got, KeyExposure)]
    if reads:
        return ("known", reads[0])
    words = {
        key: got.probe_error for key, got in outcomes.items() if isinstance(got, KeyReadFailed)
    }
    no_answer = sorted(key for key, word in words.items() if word in _NO_ANSWER)
    answered = sorted(key for key, word in words.items() if word in _ANSWERED)
    if no_answer:
        return ("failed", 503, words[no_answer[0]], None)
    if answered:
        first = outcomes[answered[0]]
        assert isinstance(first, KeyReadFailed)
        return ("failed", 502, first.probe_error, first.ret_code)
    if any(word in {"ip_not_allowed", "permission_denied"} for word in words.values()):
        return ("unknown", "fix_key")
    return ("unknown", "leave_positions")


def _shape(got: ExposureKnown | ExposureUnknown | ExposureFailed) -> tuple[Any, ...]:
    if isinstance(got, ExposureKnown):
        return ("known", got.key_id)
    if isinstance(got, ExposureFailed):
        return ("failed", got.status, got.probe_error, got.ret_code)
    return ("unknown", got.remedy)


@given(st.dictionaries(st.uuids(), _OUTCOME, max_size=6))
def test_decide_random_outcomes_match_reference_order(
    outcomes: dict[UUID, KeyExposure | KeyReadFailed],
) -> None:
    assert _shape(decide(outcomes)) == _model(outcomes)


@given(st.dictionaries(st.uuids(), _OUTCOME, max_size=6))
def test_decide_random_outcomes_never_dead_while_a_key_failed_read(
    outcomes: dict[UUID, KeyExposure | KeyReadFailed],
) -> None:
    got = decide(outcomes)
    failed_read = any(
        isinstance(o, KeyReadFailed) and o.probe_error in UNAVAILABLE | EXCHANGE_ERROR
        for o in outcomes.values()
    )
    if failed_read:
        assert not isinstance(got, ExposureUnknown)


# -- tied to 22's text --


def _text() -> str:
    spec = load_openapi_spec()
    return " ".join(spec["components"]["parameters"]["OpenExposure"]["description"].split())


def _words(phrase: str) -> set[str]:
    return set(re.findall(r"`(\w+)`", phrase))


def test_contract_groups_partition_key_probe_error_enum() -> None:
    enum = load_openapi_spec()["components"]["schemas"]["KeyProbeError"]["enum"]
    groups = [DEAD, FIXABLE, UNAVAILABLE, EXCHANGE_ERROR]
    assert sum(len(group) for group in groups) == len(PROBE_ERRORS) == len(enum)
    assert PROBE_ERRORS == set(enum)


def test_contract_failed_read_groups_match_22_text() -> None:
    text = _text()
    listed = r"((?:`\w+`(?:, | and )?)+)"
    no_answer = re.search(
        listed + r", where the exchange gave no answer, give `503 exchange_unavailable`", text
    )
    answered = re.search(
        listed + r", where it answered with an error, give `502 exchange_error`", text
    )
    vault = re.search(
        r"`(\w+)`, where the vault refused to sign .{0,80}also gives `503 exchange_unavailable`",
        text,
    )
    assert no_answer and answered and vault
    assert _words(no_answer.group(1)) | {vault.group(1)} == UNAVAILABLE
    assert _words(answered.group(1)) == EXCHANGE_ERROR
    assert "Keys that fail both ways give the `503`" in text


def test_contract_refusal_groups_match_22_text() -> None:
    text = _text()
    dead = re.search(
        r"Only a credential the exchange no longer accepts \(`(\w+)`\) makes a key dead", text
    )
    fixable = re.search(r"\*\*Fixable\.\*\* `(\w+)` \([^)]*\) and `(\w+)` are put right", text)
    assert dead and fixable
    assert {dead.group(1)} == DEAD and set(fixable.groups()) == FIXABLE


def test_contract_order_rule_matches_22_text() -> None:
    text = _text()
    for step in (
        "(1) a signable key reads the exposure",
        "(2) else any signable key gives a failed read",
        "(3) else any signable key answers a fixable refusal",
        "(4) else the account is dead",
        "an account is dead when every one of its signable keys is dead, or when it has none",
        "`Problem.exchange` holds `ret_code` only (omitted when the exchange sent none)",
    ):
        assert step in text, step
