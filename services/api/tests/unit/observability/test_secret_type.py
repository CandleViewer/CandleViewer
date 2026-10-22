"""Tests for `candleviewer.observability.secret_type.Secret` (SR-007)."""

from __future__ import annotations

import hmac

import pytest

from candleviewer.observability.secret_type import Secret


def test_str_never_prints_the_wrapped_value() -> None:
    s = Secret("CANARY-SECRET")
    assert "CANARY-SECRET" not in str(s)
    assert str(s) == "[redacted]"


def test_repr_never_prints_the_wrapped_value() -> None:
    s = Secret("CANARY-SECRET")
    assert "CANARY-SECRET" not in repr(s)


def test_format_never_prints_the_wrapped_value() -> None:
    s = Secret("CANARY-SECRET")
    assert "CANARY-SECRET" not in f"{s}"
    assert "CANARY-SECRET" not in format(s, "")


def test_fstring_interpolation_never_leaks_the_value() -> None:
    s = Secret("CANARY-SECRET")
    message = f"key is {s}"
    assert "CANARY-SECRET" not in message


def test_reveal_returns_the_original_value() -> None:
    s = Secret("CANARY-SECRET")
    assert s.reveal() == "CANARY-SECRET"


def test_equality_compares_wrapped_values() -> None:
    assert Secret("a") == Secret("a")
    assert Secret("a") != Secret("b")


def test_equals_constant_time_compares_str_values_through_compare_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SR-043 / M2 R10: two `str` secrets compare over their encoded bytes with
    `hmac.compare_digest`, and neither side is revealed on the way."""
    compared: list[tuple[bytes, bytes]] = []
    compare_digest = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        compared.append((a, b))
        return compare_digest(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    monkeypatch.setattr(Secret, "reveal", lambda self: pytest.fail("reveal() was called"))
    assert Secret("CANARY-SECRET").equals_constant_time(Secret("CANARY-SECRET"))
    assert not Secret("CANARY-SECRET").equals_constant_time(Secret("CANARY-OTHER"))
    assert not Secret("CANARY-SECRET").equals_constant_time(Secret(""))
    assert compared == [
        (b"CANARY-SECRET", b"CANARY-SECRET"),
        (b"CANARY-SECRET", b"CANARY-OTHER"),
        (b"CANARY-SECRET", b""),
    ]


def test_equals_constant_time_compares_bytes_values() -> None:
    assert Secret(b"\x00\xff").equals_constant_time(Secret(b"\x00\xff"))
    assert not Secret(b"\x00\xff").equals_constant_time(Secret(b"\x00\xfe"))


@pytest.mark.parametrize(
    ("mine", "theirs"),
    [(1, 1), ("a", b"a"), (b"a", "a"), (None, None), (("a",), ("a",))],
    ids=["int", "str-vs-bytes", "bytes-vs-str", "none", "tuple"],
)
def test_equals_constant_time_refuses_any_other_value_type(mine: object, theirs: object) -> None:
    """No fall-back to the values' own `==`, which is not constant time."""
    with pytest.raises(TypeError, match="two str secrets or two bytes secrets"):
        Secret(mine).equals_constant_time(Secret(theirs))
