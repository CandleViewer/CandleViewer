"""`Secret[T]` for credential plaintext (E27-T02, SR-007).

Subclasses the observability `Secret` so every sink registered for it (log redaction,
Problem bodies, trace attributes, support bundles) treats this one the same. Renders as
`***`; refuses pickling and copying; inside a pydantic model it always serialises as `***`.
Equality is identity-only (no plaintext comparison oracle). `invalidate()` drops the
reference after a borrow so a retained handle cannot reveal again.
"""

from __future__ import annotations

from typing import Any, NoReturn

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

from candleviewer.observability.secret_type import Secret as _ObsSecret

MASK = "***"
_GONE = object()


class Secret[T](_ObsSecret[T]):
    __slots__ = ()

    def reveal(self) -> T:
        value = self._value
        if value is _GONE:
            raise RuntimeError("secret was invalidated after its borrow ended")
        return value

    def invalidate(self) -> None:
        self._value = _GONE  # type: ignore[assignment]  # sentinel; reveal() refuses it

    def __str__(self) -> str:
        return MASK

    def __repr__(self) -> str:
        return MASK

    def __format__(self, format_spec: str) -> str:
        return MASK

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)

    def model_dump(self, *args: object, **kwargs: object) -> NoReturn:
        raise TypeError("Secret cannot be serialised")

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("Secret cannot be pickled")

    def __copy__(self) -> NoReturn:
        raise TypeError("Secret cannot be copied")

    def __deepcopy__(self, memo: object) -> NoReturn:
        raise TypeError("Secret cannot be copied")

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.is_instance_schema(
            cls,
            serialization=core_schema.plain_serializer_function_ser_schema(lambda _v: MASK),
        )
