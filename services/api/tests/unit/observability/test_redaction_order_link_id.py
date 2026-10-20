"""#3865 (E29 G-5, SR-E29-16, OM-R06): the log redactor's typed pass for `order_link_id`.

A value under the key `order_link_id` is kept only when it fully matches a
`24-internal-schemas.md` §8.3 form (`OUR_ID`, `EXT_ID`); anything else under that key, and any
value under another key or in the message, is scanned exactly as before. AC-24 is the seed.
"""

from __future__ import annotations

import io
import json
import logging
import string
from contextlib import redirect_stdout
from typing import Any, get_args

import pytest
import structlog
from hypothesis import assume, given
from hypothesis import strategies as st

from candleviewer.domain.order_link import EXT_ID, OUR_ID, ext_key
from candleviewer.domain.primitives import AccountId, Environment, GroupId
from candleviewer.observability.logging import RedactionFilter, configure_logging, reset_logging
from candleviewer.observability.redaction import _redact_mapping, _redact_str_value
from candleviewer.observability.secret_type import Secret
from candleviewer.oms.order_link import PURPOSE_TAG, SEQ_MAX, OrderLinkIdParts

OUR = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the §8.3 worked example
EXT = ext_key("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d")
CANARY = "CANARYxx0123456789abcdefXYZ"  # synthetic: 27 alphanumerics
KEY_SHAPE = "[redacted:key-shape]"


def _under(value: object, key: str = "order_link_id") -> Any:
    return _redact_mapping({key: value})[key]


def _full(value: str) -> bool:
    return OUR_ID.fullmatch(value) is not None or EXT_ID.fullmatch(value) is not None


def test_redactor_ac24_keeps_the_id_and_redacts_a_secret_under_the_same_key() -> None:
    assert _redact_str_value(OUR) == KEY_SHAPE  # OM-R06: the scan alone masks the id
    assert _redact_mapping({"order_link_id": OUR}) == {"order_link_id": OUR}
    assert _redact_mapping({"order_link_id": CANARY}) == {"order_link_id": KEY_SHAPE}


def test_logging_ac24_json_lines_keep_the_id_and_redact_the_secret() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        configure_logging(env="test", level="info", fmt="json")
        log = structlog.get_logger("oms")
        log.info("oms_order_created", order_link_id=OUR)
        log.info("oms_order_created", order_link_id=CANARY)
        reset_logging()  # stops the listener once it has written the queue out
    lines = [json.loads(line) for line in buf.getvalue().splitlines()]
    assert [line["order_link_id"] for line in lines] == [OUR, KEY_SHAPE]
    assert CANARY not in buf.getvalue()


@pytest.mark.parametrize("link", [OUR, EXT], ids=["generated", "ext"])
def test_redactor_a_generated_or_ext_id_survives(link: str) -> None:
    assert _full(link)
    assert _under(link) == link


@pytest.mark.parametrize(
    "value",
    [
        CANARY,
        "a" * 18,
        "Z9" * 18,
        OUR + "\n",  # `$` also matches before a trailing newline; `fullmatch` does not
        EXT + "\n",
        "\n" + OUR,
        OUR + "x",
        "x" + OUR,
        f" {OUR} ",
        f"sent {OUR} twice",
        OUR[:-1],
        OUR.upper(),
        EXT.upper(),
        OUR[:33] + "\u0663" + OUR[34:],  # an Arabic-Indic digit
        "\uff43" + OUR[1:],  # a fullwidth "c"
        "ext-" + "g" * 32,
    ],
)
def test_redactor_a_secret_or_partial_match_under_the_key_is_redacted(value: str) -> None:
    assert not _full(value)
    assert _under(value) == KEY_SHAPE


@pytest.mark.parametrize(  # `orderLinkId` too: the wire name, which no log line on main carries
    "key", ["orderLinkId", "ORDER_LINK_ID", "order_link_id ", "order_link_ids", "client_order_id"]
)
def test_redactor_an_id_under_any_other_key_is_redacted(key: str) -> None:
    assert (_under(OUR, key), _under(EXT, key)) == (KEY_SHAPE, KEY_SHAPE)


def test_redactor_an_id_in_the_message_is_redacted_beside_the_kept_key() -> None:
    out = _redact_mapping({"event": f"order {OUR} sent", "order_link_id": OUR})
    assert out == {"event": KEY_SHAPE, "order_link_id": OUR}


def test_redactor_nested_dicts_follow_the_rule_and_a_list_under_the_key_is_scanned() -> None:
    legs = [{"order_link_id": EXT}, {"order_link_id": CANARY}]
    out = _redact_mapping({"payload": {"order_link_id": OUR, "legs": legs}})
    redacted_legs = [{"order_link_id": EXT}, {"order_link_id": KEY_SHAPE}]
    assert out == {"payload": {"order_link_id": OUR, "legs": redacted_legs}}
    assert (_under([OUR, EXT]), _under((OUR,))) == ([KEY_SHAPE, KEY_SHAPE], (KEY_SHAPE,))


class _Text(str):
    """A `str` subclass can render as anything, so it never gets the pass."""


class _AnyKey(str):
    """A key that claims to equal every key."""

    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = str.__hash__


def test_redactor_a_str_subclass_a_non_str_value_and_a_lying_key_get_no_pass() -> None:
    assert _under(_Text(OUR)) == KEY_SHAPE
    assert (_under(Secret(OUR)), _under(OUR.encode()), _under(7)) == ("***", "[redacted:bytes]", 7)
    assert list(_redact_mapping({_AnyKey("client_order_id"): OUR}).values()) == [KEY_SHAPE]


def test_redaction_filter_passes_an_id_in_mapping_args_and_scans_the_rest() -> None:
    kept = logging.LogRecord(
        "x", logging.INFO, "", 1, "%(order_link_id)s", ({"order_link_id": OUR},), None
    )
    masked = logging.LogRecord("x", logging.INFO, "", 1, f"{OUR} %s", (OUR,), None)
    assert RedactionFilter().filter(kept) and RedactionFilter().filter(masked)
    assert kept.getMessage() == OUR
    assert (masked.msg, masked.args) == (KEY_SHAPE, (KEY_SHAPE,))


_GENERATED = st.builds(
    OrderLinkIdParts.generate,
    mode=st.sampled_from(("exchange", "paper")),
    environment=st.sampled_from(get_args(Environment)),
    group_id=st.uuids().map(GroupId),
    account_id=st.uuids().map(AccountId),
    seq=st.integers(0, SEQ_MAX),
    purpose=st.sampled_from(tuple(PURPOSE_TAG)),
).map(lambda parts: parts.value)
_IDS = st.one_of(_GENERATED, st.one_of(st.uuids().map(str), st.text()).map(ext_key))
#: An id with one character inserted, replaced or deleted (`""` with `replace`).
_CHARS = ["", "\n", " ", "-", "x", "0", "\u0663"]
_EDIT = st.tuples(st.integers(0, 36), st.sampled_from(_CHARS), st.booleans())


def _edited(case: tuple[str, tuple[int, str, bool]]) -> str:
    link, (at, char, replace) = case
    return link[:at] + char + link[at + replace :]


@given(_IDS)
def test_redactor_every_id_the_generators_produce_survives(link: str) -> None:
    assert _redact_mapping({"order_link_id": link}) == {"order_link_id": link}


@given(st.text(string.ascii_letters + string.digits, min_size=18, max_size=36))
def test_redactor_every_18_to_36_alphanumeric_secret_under_the_key_is_redacted(value: str) -> None:
    assume(not _full(value))
    assert _under(value) == KEY_SHAPE


@given(st.one_of(st.text(), st.tuples(_IDS, _EDIT).map(_edited)))
def test_redactor_a_value_that_is_not_a_full_match_is_scanned_as_before(value: str) -> None:
    assume(not _full(value))
    assert _under(value) == _redact_str_value(value)
