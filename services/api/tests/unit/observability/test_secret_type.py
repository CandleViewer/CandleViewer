"""Tests for `candleviewer.observability.secret_type.Secret` (SR-007)."""

from __future__ import annotations

import hmac

import pytest

from candleviewer.observability.secret_type import ComparableSecret, Secret


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


def _spy_compare_digest(monkeypatch: pytest.MonkeyPatch) -> list[tuple[bytes, bytes]]:
    compared: list[tuple[bytes, bytes]] = []
    compare_digest = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        compared.append((a, b))
        return compare_digest(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    return compared


def test_equals_constant_time_compares_str_values_through_compare_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SR-043 / M2 R10: two `str` secrets compare over their encoded bytes with
    `hmac.compare_digest`, and neither side is revealed on the way."""
    compared = _spy_compare_digest(monkeypatch)
    monkeypatch.setattr(Secret, "reveal", lambda self: pytest.fail("reveal() was called"))
    held = ComparableSecret("CANARY-SECRET")
    assert held.equals_constant_time(ComparableSecret("CANARY-SECRET"))
    assert not held.equals_constant_time(ComparableSecret("CANARY-OTHER"))
    assert not held.equals_constant_time(ComparableSecret(""))
    assert compared == [
        (b"CANARY-SECRET", b"CANARY-SECRET"),
        (b"CANARY-SECRET", b"CANARY-OTHER"),
        (b"CANARY-SECRET", b""),
    ]


def test_equals_constant_time_encodes_non_ascii_values_as_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A value outside ASCII is compared over its UTF-8 bytes, never refused or truncated."""
    compared = _spy_compare_digest(monkeypatch)
    accented, plain = "clé → k", "cle → k"
    assert ComparableSecret(accented).equals_constant_time(ComparableSecret(accented))
    assert not ComparableSecret(accented).equals_constant_time(ComparableSecret(plain))
    assert compared == [
        (accented.encode("utf-8"), accented.encode("utf-8")),
        (accented.encode("utf-8"), plain.encode("utf-8")),
    ]


def test_equals_constant_time_compares_bytes_values_through_compare_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compared = _spy_compare_digest(monkeypatch)
    low, high, other = bytes([0, 255]), bytes([0, 255]), bytes([0, 254])
    assert ComparableSecret(low).equals_constant_time(ComparableSecret(high))
    assert not ComparableSecret(low).equals_constant_time(ComparableSecret(other))
    assert compared == [(low, high), (low, other)]


@pytest.mark.parametrize(
    ("mine", "theirs"),
    [(1, 1), ("a", b"a"), (b"a", "a"), (None, None), (("a",), ("a",))],
    ids=["int", "str-vs-bytes", "bytes-vs-str", "none", "tuple"],
)
def test_equals_constant_time_refuses_any_other_value_type(mine: object, theirs: object) -> None:
    """No fall-back to the values' own `==`, which is not constant time."""
    with pytest.raises(TypeError, match="two str secrets or two bytes secrets"):
        ComparableSecret(mine).equals_constant_time(ComparableSecret(theirs))


def test_the_base_secret_offers_no_comparison_oracle() -> None:
    """Only `ComparableSecret` compares values. The base `Secret` — and so M2's credential
    `Secret`, which extends the base, not this subclass — exposes no `equals_constant_time`."""
    assert not hasattr(Secret("CANARY-SECRET"), "equals_constant_time")
    assert "equals_constant_time" not in vars(Secret)
    assert issubclass(ComparableSecret, Secret)
