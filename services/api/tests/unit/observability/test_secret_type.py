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
    """Only `ComparableSecret` offers `equals_constant_time`. The base `Secret` — and so M2's
    credential `Secret`, which extends the base, not this subclass — exposes no such method; the
    base compares values only between two secrets of exactly its own class (pinned below)."""
    assert not hasattr(Secret("CANARY-SECRET"), "equals_constant_time")
    assert "equals_constant_time" not in vars(Secret)
    assert issubclass(ComparableSecret, Secret)


class _Guarded(Secret[str]):
    """A stand-in for a subclass whose value must never be probed through the base (M2)."""

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)


def test_equality_never_crosses_secret_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A base or comparable secret never equals a secret of another class, in either operand
    order, whatever the values — so no sibling class can be used to probe a guarded value."""
    monkeypatch.setattr(Secret, "reveal", lambda self: pytest.fail("reveal() was called"))
    guarded = _Guarded("CANARY-SECRET")
    for probe in (Secret("CANARY-SECRET"), ComparableSecret("CANARY-SECRET")):
        assert probe != guarded
        assert guarded != probe
        assert not (probe == guarded)
        assert not (guarded == probe)
    assert Secret("CANARY-SECRET") != ComparableSecret("CANARY-SECRET")
    assert ComparableSecret("CANARY-SECRET") != Secret("CANARY-SECRET")


class _Plain(Secret[str]):
    """A subclass that keeps the base `__eq__`, so the base's own class check is what runs."""

    __slots__ = ()


def test_the_base_equality_never_crosses_classes_even_without_an_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The base `__eq__` itself refuses another class: with no subclass override in the way,
    Python reaches the base check, and it answers False for a different `Secret` class."""
    monkeypatch.setattr(Secret, "reveal", lambda self: pytest.fail("reveal() was called"))
    plain, base = _Plain("CANARY-SECRET"), Secret("CANARY-SECRET")
    assert plain != base and base != plain
    assert not (plain == base) and not (base == plain)
    assert _Plain("CANARY-SECRET") == _Plain("CANARY-SECRET")
    assert Secret.__eq__(base, _Guarded("CANARY-SECRET")) is False
    assert Secret.__eq__(base, ComparableSecret("CANARY-SECRET")) is False
    assert Secret.__eq__(base, "CANARY-SECRET") is NotImplemented


def test_equals_constant_time_refuses_any_other_kind_of_secret() -> None:
    guarded = _Guarded("CANARY-SECRET")
    # The static type already refuses these operands; the test pins the runtime refusal too.
    with pytest.raises(TypeError, match="two ComparableSecret values"):
        ComparableSecret("CANARY-SECRET").equals_constant_time(guarded)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="two ComparableSecret values"):
        ComparableSecret("CANARY-SECRET").equals_constant_time(
            Secret("CANARY-SECRET")  # type: ignore[arg-type]
        )


def test_comparable_secrets_compare_through_the_constant_time_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`==` on two comparable secrets is the constant-time comparison, never the values' own."""
    compared = _spy_compare_digest(monkeypatch)
    assert ComparableSecret("CANARY-SECRET") == ComparableSecret("CANARY-SECRET")
    assert ComparableSecret("CANARY-SECRET") != ComparableSecret("CANARY-OTHER")
    assert compared == [
        (b"CANARY-SECRET", b"CANARY-SECRET"),
        (b"CANARY-SECRET", b"CANARY-OTHER"),
    ]
    assert ComparableSecret("CANARY-SECRET") != "CANARY-SECRET"
    assert hash(ComparableSecret("a")) == hash(ComparableSecret("b"))
    assert len({ComparableSecret("a"), ComparableSecret("a"), ComparableSecret("b")}) == 2
