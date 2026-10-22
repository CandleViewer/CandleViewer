"""`Secret[str]`-style wrapper (SR-007) — defence in depth for the key store.

Not a replacement for `pydantic.SecretStr` (already used in `settings.py`);
this is a light generic wrapper for values that flow through non-pydantic
code paths (e.g. the secrets module's in-memory plaintext handling) where a
`__repr__`/`__str__`/`__format__` that always redacts is the cheapest
guarantee against an accidental `logger.info(f"key={key}")`-style leak.
"""

from __future__ import annotations

import hmac

_REDACTED = "[redacted]"


class Secret[T]:
    """Wraps a sensitive value so accidental logging never prints it.

    `.reveal()` is the only way to get the plaintext back out — a call site
    that wants the real value has to say so explicitly, which is easy to
    grep for in review.
    """

    __slots__ = ("_value",)

    def __init__(self, value: T) -> None:
        self._value = value

    def reveal(self) -> T:
        """Return the wrapped plaintext value. The only intentional escape hatch."""
        return self._value

    def equals_constant_time(self, other: Secret[T]) -> bool:
        """Whether two secrets hold the same `str` or `bytes` value, compared in constant time
        (`hmac.compare_digest` over the encoded bytes), so the time the comparison takes tells
        nothing of how much of a presented value matches (SR-043). Neither value is revealed, so
        a caller outside `secrets/` can compare without the plaintext (M2 R10). Any other value
        type raises `TypeError`: there is no fall-back to the values' own `==`."""
        mine, theirs = self._value, other._value
        if isinstance(mine, str) and isinstance(theirs, str):
            return hmac.compare_digest(mine.encode(), theirs.encode())
        if isinstance(mine, bytes) and isinstance(theirs, bytes):
            return hmac.compare_digest(mine, theirs)
        raise TypeError("equals_constant_time compares two str secrets or two bytes secrets")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return _REDACTED

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Secret({_REDACTED})"

    def __format__(self, format_spec: str) -> str:  # pragma: no cover - trivial
        return _REDACTED

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            return self._value == other._value  # type: ignore[no-any-return]
        return NotImplemented

    def __hash__(self) -> int:
        return hash(("Secret", id(self)))
