"""`refuse_unstorable_text`: U+0000 and lone surrogates are refused with a fixed message that
never echoes the input; any other text, other control characters included, passes unchanged, and
so does a value that is not a `str`."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from candleviewer.domain.text import UNSTORABLE_TEXT, refuse_unstorable_text

#: Text Postgres stores: everything but U+0000 and surrogates (other controls included).
_STORABLE = st.text(st.characters(codec="utf-8", exclude_characters="\x00"))


@pytest.mark.parametrize("bad", ["\x00", chr(0xD800), chr(0xDFFF)])
@given(head=_STORABLE, tail=_STORABLE)
def test_refuse_unstorable_text_refuses_nul_and_lone_surrogates(
    bad: str, head: str, tail: str
) -> None:
    with pytest.raises(ValueError) as refused:
        refuse_unstorable_text(head + bad + tail)
    assert str(refused.value) == UNSTORABLE_TEXT


@given(text=_STORABLE)
@example(text="\x01\x1b\x7f" + chr(0xE9) + chr(0x1F600))
def test_refuse_unstorable_text_returns_storable_text_unchanged(text: str) -> None:
    assert refuse_unstorable_text(text) is text


@pytest.mark.parametrize("value", [None, 1, b"\x00", ["\x00"]])
def test_refuse_unstorable_text_returns_a_value_that_is_not_a_str_unchanged(value: Any) -> None:
    assert refuse_unstorable_text(value) is value
