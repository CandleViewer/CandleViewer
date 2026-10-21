"""A fake identity read path for the owner-gate tests (#3349): no database, no real clock."""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Iterable


class Directory:
    """`OwnerDirectory` fake: the `active` owners (`everyone`: all of them), what each read raises
    (`fail`) or whether it hangs, and `reads`, the set each read asked about."""

    def __init__(self, active: Iterable[str] = (), *, everyone: bool = False,
                 fail: BaseException | None = None, hang: bool = False) -> None:  # fmt: skip
        self.active, self.everyone, self.fail, self.hang = set(active), everyone, fail, hang
        self.reads: list[frozenset[str]] = []

    async def active_users(self, user_ids: Collection[str]) -> frozenset[str]:
        self.reads.append(frozenset(user_ids))
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
