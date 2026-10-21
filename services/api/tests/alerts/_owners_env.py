"""A fake identity read path for the owner-gate tests (#3349): no database, no real clock."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection, Iterable

from candleviewer.alerts.owners import OwnerGate


class Directory:
    """`OwnerDirectory` fake: the `active` owners (`everyone`: all of them), what each read raises
    (`fail`) or whether it hangs, `reads`, the set each asked, and `on_read`, run as each starts."""

    def __init__(self, active: Iterable[str] = (), *, everyone: bool = False,
                 fail: BaseException | None = None, hang: bool = False) -> None:  # fmt: skip
        self.active, self.everyone, self.fail, self.hang = set(active), everyone, fail, hang
        self.reads: list[frozenset[str]] = []
        self.on_read: Callable[[], None] = lambda: None

    async def active_users(self, user_ids: Collection[str]) -> frozenset[str]:
        self.reads.append(frozenset(user_ids))
        self.on_read()
        if self.hang:
            await asyncio.Event().wait()
        if self.fail is not None:
            raise self.fail
        return frozenset(user_ids if self.everyone else self.active.intersection(user_ids))


class Time:
    """The gate's monotonic clock, moved by hand."""

    now = 0.0

    def __call__(self) -> float:
        return self.now


def allow() -> OwnerGate:
    """A gate that finds every owner active, for the tests that are not about the owner."""
    return OwnerGate(Directory(everyone=True))
