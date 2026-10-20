"""Fixtures for cv-admin-mutation-audited in a file with PEP 695 generics, which Semgrep parses
another way (#3549, X03-F4): the rule must hold here too (D10)."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from candleviewer.admin.audited import audit_exempt, audited


def first[T](items: list[T]) -> T:
    return items[0]


class Tally:
    async def run[T](self, op: Callable[[], Awaitable[T]]) -> T:  # ruleid: cv-admin-mutation-audited
        return await op()

    async def drain(self) -> None:  # ruleid: cv-admin-mutation-audited
        ...

    @audited("users.disable")  # ok: cv-admin-mutation-audited
    async def disable[T](self, user_id: T) -> T:
        return user_id

    @audit_exempt("lifecycle")  # ok: cv-admin-mutation-audited
    async def stop(self) -> None:
        ...


class Box[T]:
    def get(self) -> T:  # ruleid: cv-admin-mutation-audited
        ...

    @staticmethod  # ruleid: cv-admin-mutation-audited
    def pick[U](items: list[U]) -> U:
        return items[0]

    @classmethod  # ruleid: cv-admin-mutation-audited
    def empty(cls) -> "Box[T]":
        return cls()


class Port[T](Protocol):
    async def put(self, item: T) -> None: ...  # ok: cv-admin-mutation-audited
