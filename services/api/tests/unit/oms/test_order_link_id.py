"""§8.3 `order_link_id` generator and parser (E29-T02, #846): scenario "Deterministic
and bounded" and the ticket test plan, including the <50 µs generation budget."""

from __future__ import annotations

import hashlib
import re
import statistics
import time
import zlib
from typing import cast, get_args
from uuid import UUID

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from candleviewer.domain.order_link import OUR_ID
from candleviewer.domain.primitives import AccountId, Environment, ExecutionMode, GroupId
from candleviewer.oms.errors import (
    InvalidOrderLinkId,
    OmsError,
    OrderLinkIdExhausted,
    UnsupportedExecutionMode,
)
from candleviewer.oms.order_link import (
    BASE62,
    PURPOSE_TAG,
    SEQ_MAX,
    EnvLetter,
    OrderLinkIdParts,
    OrderPurpose,
    PurposeTag,
    account_tag,
    env_letter,
)

AC_PATTERN = re.compile(r"^cv-?[a-zA-Z0-9_-]+$")  # the scenario's own pattern
CHARSET = re.compile(r"^[A-Za-z0-9_-]{1,36}$")  # the exchange limit, as the `OrderLinkId` alias
GROUP = UUID("0f8e2b6c-3d4a-4b5c-9e7f-1a2b3c4d5e6f")  # the §8.3 worked example
ACCOUNT = UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d")
EXAMPLE = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"
MODES: tuple[ExecutionMode, ...] = ("exchange", "paper")  # replay has no letter
ENVIRONMENTS: tuple[Environment, ...] = get_args(Environment)
PURPOSES: tuple[OrderPurpose, ...] = get_args(OrderPurpose)

type Inputs = tuple[UUID, UUID, ExecutionMode, Environment, int, OrderPurpose]
inputs = st.tuples(
    st.uuids(),
    st.uuids(),
    st.sampled_from(MODES),
    st.sampled_from(ENVIRONMENTS),
    st.integers(min_value=0, max_value=SEQ_MAX),
    st.sampled_from(PURPOSES),
)


def _generate(
    group: UUID = GROUP,
    account: UUID = ACCOUNT,
    mode: ExecutionMode = "exchange",
    environment: Environment = "live",
    seq: int = 0,
    purpose: OrderPurpose = "entry",
) -> OrderLinkIdParts:
    return OrderLinkIdParts.generate(
        mode=mode,
        environment=environment,
        group_id=GroupId(group),
        account_id=AccountId(account),
        seq=seq,
        purpose=purpose,
    )


def _decode(text: str) -> int:
    return sum(BASE62.index(char) * 62**power for power, char in enumerate(reversed(text)))


def test_generate_reproduces_the_contract_example() -> None:
    assert _generate().value == EXAMPLE


@given(inputs)
def test_deterministic_and_bounded(args: Inputs) -> None:
    """Scenario: Deterministic and bounded."""
    first, second = _generate(*args).value, _generate(*args).value

    assert first == second
    assert len(first) == 36
    assert AC_PATTERN.fullmatch(first) is not None
    assert CHARSET.fullmatch(first) is not None
    assert OUR_ID.fullmatch(first) is not None


def test_length_and_charset_hold_for_10000_ids() -> None:
    for i in range(10_000):
        group, account = (UUID(bytes=hashlib.sha256(b"%d%c" % (i, s)).digest()[:16]) for s in b"ga")
        value = _generate(
            group, account, "exchange", ENVIRONMENTS[i % 3], i % (SEQ_MAX + 1), PURPOSES[i % 8]
        ).value

        assert len(value) == 36
        assert CHARSET.fullmatch(value) is not None


@pytest.mark.parametrize(
    ("mode", "environment", "letter"),
    [("exchange", "live", "l"), ("exchange", "demo", "d"), ("exchange", "testnet", "t")]
    + [("paper", environment, "p") for environment in ENVIRONMENTS],
)
def test_env_letter_comes_from_the_order(
    mode: ExecutionMode, environment: Environment, letter: EnvLetter
) -> None:
    assert env_letter(mode, environment) == letter
    assert _generate(mode=mode, environment=environment).value[2] == letter


def test_paper_and_demo_ids_for_the_same_group_differ() -> None:
    assert _generate(mode="paper", environment="demo") != _generate(environment="demo")


def test_replay_fails_closed_with_a_typed_oms_error() -> None:
    with pytest.raises(UnsupportedExecutionMode):
        _generate(mode="replay")


@pytest.mark.parametrize(
    "error", [InvalidOrderLinkId, UnsupportedExecutionMode, OrderLinkIdExhausted]
)
def test_order_link_errors_are_typed_oms_errors(error: type[Exception]) -> None:
    assert issubclass(error, OmsError)


@pytest.mark.parametrize(
    ("purpose", "tag"),
    [
        ("entry", "en"),
        ("reverse", "en"),
        ("stop_loss", "sl"),
        ("take_profit", "tp"),
        ("scale_in", "sc"),
        ("scale_out", "sc"),
        ("flatten", "fl"),
        ("algo_child", "ac"),
    ],
)
def test_purpose_maps_to_its_suffix(purpose: OrderPurpose, tag: PurposeTag) -> None:
    assert _generate(purpose=purpose).value[34:] == tag


def test_every_intent_purpose_maps_onto_the_six_tags() -> None:
    assert set(PURPOSE_TAG) == set(PURPOSES)
    assert set(PURPOSE_TAG.values()) == {"en", "sl", "tp", "sc", "fl", "ac"}


def test_account_tag_reduces_crc32_modulo_62_to_the_4() -> None:
    crc = zlib.crc32(str(ACCOUNT).encode("ascii"))

    assert crc >= 62**4  # the reduction is exercised, not a no-op
    assert account_tag(AccountId(ACCOUNT)) == "d0hb"
    assert _decode("d0hb") == crc % 62**4


@given(st.uuids())
def test_account_tag_is_four_base62_digits_of_the_reduced_crc32(account: UUID) -> None:
    tag = account_tag(AccountId(account))

    assert len(tag) == 4
    assert _decode(tag) == zlib.crc32(str(account).lower().encode("ascii")) % 62**4


@pytest.mark.parametrize(("group", "prefix"), [(0, "0" * 22), (2**128 - 1, "7")])
def test_group_segment_spans_zero_padding_to_the_128_bit_maximum(group: int, prefix: str) -> None:
    value = _generate(UUID(int=group)).value

    assert value[4:26].startswith(prefix)
    assert _decode(value[4:26]) == group


@pytest.mark.parametrize(("seq", "digits"), [(0, "00"), (61, "0z"), (62, "10"), (SEQ_MAX, "zz")])
def test_seq_renders_as_two_base62_digits(seq: int, digits: str) -> None:
    assert _generate(seq=seq).value[32:34] == digits


@pytest.mark.parametrize("seq", [-1, SEQ_MAX + 1])
def test_seq_outside_0_to_3843_is_rejected(seq: int) -> None:
    with pytest.raises(InvalidOrderLinkId, match=r"outside 0\.\.3843"):
        _generate(seq=seq)


@pytest.mark.parametrize(
    ("env", "account", "tag"),
    [("x", "d0hb", "en"), ("l", "d0h", "en"), ("l", "d0-b", "en"), ("l", "d0hb", "zz")],
)
def test_parts_that_cannot_render_a_generated_id_are_rejected(
    env: str, account: str, tag: str
) -> None:
    with pytest.raises(InvalidOrderLinkId):
        OrderLinkIdParts(cast(EnvLetter, env), GroupId(GROUP), account, 0, cast(PurposeTag, tag))


def test_with_seq_changes_only_seq2() -> None:
    parts = _generate(seq=5)

    assert parts.with_seq(6).value == parts.value[:32] + "06" + parts.value[34:]


@given(inputs)
def test_parse_round_trips_a_generated_id(args: Inputs) -> None:
    parts = _generate(*args)

    parsed = OrderLinkIdParts.parse(parts.value)

    assert parsed == parts  # env, group, account tag, seq and purpose tag all compare
    assert parsed.value == parts.value
    assert (parsed.group_id, parsed.seq) == (args[0], args[4])


@given(st.from_regex(OUR_ID, fullmatch=True))
def test_parse_round_trips_every_our_id_that_fits_128_bits(value: str) -> None:
    assume(_decode(value[4:26]) < 2**128)

    assert OrderLinkIdParts.parse(value).value == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ext-" + "0" * 32,  # an adopted row's key is not decomposable
        EXAMPLE + "\n",
        EXAMPLE[:-1],
        "cvl-7zzzzzzzzzzzzzzzzzzzzz-d0hb-00en",  # matches OUR_ID but exceeds 128 bits
    ],
)
def test_parse_rejects_a_value_the_generator_cannot_produce(value: str) -> None:
    with pytest.raises(InvalidOrderLinkId):
        OrderLinkIdParts.parse(value)


@pytest.mark.perf
def test_generation_median_is_under_50_microseconds() -> None:
    samples: list[int] = []
    for i in range(2_000):
        started = time.perf_counter_ns()
        _generate(seq=i % (SEQ_MAX + 1))
        samples.append(time.perf_counter_ns() - started)

    assert statistics.median(samples) < 50_000
