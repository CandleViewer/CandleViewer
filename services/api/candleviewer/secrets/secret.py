"""`Secret[T]` for credential plaintext (E27-T02, SR-007).

Subclasses the observability `Secret` so every sink already registered for it (log
redaction, Problem bodies, trace attributes, support bundles) treats this one the same.
Renders as `***`; refuses pydantic dumping, pickling and copying.
"""

from __future__ import annotations

from typing import NoReturn

from candleviewer.observability.secret_type import Secret as _ObsSecret

MASK = "***"


class Secret[T](_ObsSecret[T]):
    __slots__ = ()

    def __str__(self) -> str:
        return MASK

    def __repr__(self) -> str:
        return MASK

    def __format__(self, format_spec: str) -> str:
        return MASK

    def model_dump(self, *args: object, **kwargs: object) -> NoReturn:
        raise TypeError("Secret cannot be serialised")

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("Secret cannot be pickled")

    def __copy__(self) -> NoReturn:
        raise TypeError("Secret cannot be copied")

    def __deepcopy__(self, memo: object) -> NoReturn:
        raise TypeError("Secret cannot be copied")
