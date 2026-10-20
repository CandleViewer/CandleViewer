"""Fixtures for cv-admin-mutation-audited (E42-X03, D1): each public method of a non-Protocol
class under admin/ declares its audit. A finding starts at a method's first decorator."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cached_property
from typing import Protocol, TypeVar

from candleviewer.admin.audited import audit_exempt, audited

_T = TypeVar("_T")


class UserService:
    async def disable(self, user_id: str) -> None:  # ruleid: cv-admin-mutation-audited
        ...

    def replace(self, grants: dict[str, str]) -> None:  # ruleid: cv-admin-mutation-audited
        ...

    @property  # ruleid: cv-admin-mutation-audited
    def engaged(self) -> bool:
        return True

    @audited("users.disable")  # ok: cv-admin-mutation-audited
    async def disable_declared(self, user_id: str) -> None:
        ...

    @audited("backup.run", "backup.verified")  # ok: cv-admin-mutation-audited
    def start(self) -> None:
        ...

    @audit_exempt("read")  # ok: cv-admin-mutation-audited
    def page(self) -> list[str]:
        return []

    @property  # ok: cv-admin-mutation-audited
    @audit_exempt("read")
    def ready(self) -> bool:
        return True

    @cached_property  # ok: cv-admin-mutation-audited
    @audit_exempt("read")
    def registry(self) -> dict[str, str]:
        return {}

    @asynccontextmanager  # ok: cv-admin-mutation-audited
    @audit_exempt("caller_audits")
    async def serialized(self) -> AsyncIterator[None]:
        yield

    async def _commit(self) -> None:  # ok: cv-admin-mutation-audited
        ...

    @staticmethod  # ruleid: cv-admin-mutation-audited
    def build() -> "UserService":
        return UserService()

    @classmethod  # ruleid: cv-admin-mutation-audited
    def from_row(cls, row: dict[str, str]) -> "UserService":
        return cls()

    @staticmethod  # ok: cv-admin-mutation-audited
    @audit_exempt("read")
    def digest(text: str) -> str:
        return text

    @classmethod  # ok: cv-admin-mutation-audited
    @audit_exempt("wiring")
    def default(cls) -> "UserService":
        return cls()

    @staticmethod  # ok: cv-admin-mutation-audited
    def _parse(text: str) -> int:
        return len(text)


class _Helper:  # a private class's public method declares too
    async def emit(self, action: str) -> None:  # ruleid: cv-admin-mutation-audited
        ...


class Store(Protocol):
    async def replace(self, user_id: str) -> None: ...  # ok: cv-admin-mutation-audited


class Reader(Protocol[_T]):
    def read(self) -> _T: ...  # ok: cv-admin-mutation-audited


class Concrete(Store):  # implements a protocol without being one
    async def replace(self, user_id: str) -> None:  # ruleid: cv-admin-mutation-audited
        ...


def lookalike(action: str) -> object:
    return lambda fn: fn


class Undeclared:
    @lookalike("users.disable")  # ruleid: cv-admin-mutation-audited
    async def disable(self, user_id: str) -> None:
        ...
