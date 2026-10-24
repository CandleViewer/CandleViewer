"""#2188 S3c's policy members, as the orchestrator approved them (2026-10-24 12:42Z), over the real
`RecordingPolicy` until S3c is on main (then this file goes): `relax_allowed`, `set_pin` with the
view and the unpin's retention, and `set_retention`. A refused relax writes its denied record and
raises before any write; each write records `retention.change` ahead of its store. `days` writes a
row's `retention_days` (S3c's `RecordedStore.set_retention`)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from candleviewer.recorder.control_runtime import RecorderRelaxRefusedError
from candleviewer.recorder.errors import RecorderSymbolNotRecordedError
from candleviewer.recorder.models import Actor
from candleviewer.recorder.policy import RecordingPolicy

DaysWriter = Callable[[str, int | None], Awaitable[bool]]


class S3cPolicy:
    def __init__(self, policy: RecordingPolicy, days: DaysWriter, *, default_days: int) -> None:
        self.policy, self._days, self._default = policy, days, default_days

    def __getattr__(self, name: str) -> Any:  # every other member is the policy's own
        return getattr(self.policy, name)

    def relax_allowed(self, symbol: str, *, restricted: bool) -> bool:
        """A restricted view covers no row a hidden cause (a position) holds."""
        return not restricted or not self.policy.position_open(symbol)

    async def _row(self, symbol: str) -> dict[str, Any]:
        row = await self.policy._recorded.get_by_symbol(symbol, self.policy._env)
        if row is None:
            raise RecorderSymbolNotRecordedError(symbol)
        return row

    async def _refuse(self, symbol: str, actor: Actor, restricted: bool) -> None:
        if not self.relax_allowed(symbol, restricted=restricted):
            await self.policy._audit_emit("retention.change", symbol, actor,
                                          reason="relax_refused", extra={},
                                          outcome="denied")  # fmt: skip
            raise RecorderRelaxRefusedError(
                "Only the owner can unpin this row or lower its retention"
            )

    async def set_pin(self, symbol: str, pinned: bool, actor: Actor, *, restricted: bool,
                      retention_days: int | None = None) -> None:  # fmt: skip
        row = await self._row(symbol)
        if not pinned and row["pinned"]:
            await self._refuse(symbol, actor, restricted)
        await self.policy.set_pin(symbol, pinned, actor)
        await self._days(str(row["id"]), None if pinned else retention_days)

    async def set_retention(self, symbol: str, retention_days: int | None, actor: Actor, *,
                            restricted: bool) -> None:  # fmt: skip
        row = await self._row(symbol)
        held = row.get("retention_days")
        if (retention_days or self._default) < (held or self._default):
            await self._refuse(symbol, actor, restricted)
        await self.policy._audit_emit(
            "retention.change", symbol, actor, reason="retention",
            before={"retention_days": None if held is None else str(held)},
            extra={"retention_days": None if retention_days is None else str(retention_days)},
        )  # fmt: skip
        await self._days(str(row["id"]), retention_days)
