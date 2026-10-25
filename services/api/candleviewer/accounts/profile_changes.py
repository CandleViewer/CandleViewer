"""The change a committed profile write publishes (E28-T02, #906 D3a; 24 Sec.9.2): the account, the
rows the write gave a new version and those versions, never a value. A consumer re-reads what it
needs through its own scope. Propagation, not a guard: the order path's version check at submit
keeps a stale profile from sizing (SR-E28-15).

`ProfilesRepository` announces each committed write through the `ProfileChanges` port, after the
commit and the cache invalidation and bounded by `ANNOUNCE_TIMEOUT_S`; the composition root binds
the port over the bus (`profiles_wiring.BusProfileChanges`), so this module imports no bus (C-3.1).
"""

from __future__ import annotations

from typing import Final, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from candleviewer.domain.primitives import TsUs

#: One announcement's bound: a port slower than this loses the event, never the write.
ANNOUNCE_TIMEOUT_S: Final = 0.5

type ChangeKind = Literal["created", "updated", "deleted", "default_moved"]


class ProfileVersion(BaseModel):
    """A profile row and its version after the write."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: UUID
    version: int = Field(ge=1)


class ProfilesChanged(BaseModel):
    """One committed write on an account's profiles. A default move names the rows it bumped, the
    demoted default first, and the binding's version after it; any other write names its one row
    and no binding. `ts_event` is the written row's `updated_at` (the new default's on a move)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exchange_account_id: UUID
    change: ChangeKind
    profiles: tuple[ProfileVersion, ...] = Field(min_length=1, max_length=2)
    binding_version: int | None = Field(default=None, ge=1)
    ts_event: TsUs

    @model_validator(mode="after")
    def _only_a_move_names_two_rows_and_a_binding(self) -> Self:
        moved = self.change == "default_moved"
        if moved != (self.binding_version is not None) or (len(self.profiles) > 1 and not moved):
            raise ValueError("only a default move names two rows and the binding's version")
        return self


class ProfileChanges(Protocol):
    """Hears each committed profile write (bound in the composition root)."""

    async def changed(self, event: ProfilesChanged) -> None: ...
