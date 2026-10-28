"""The flatten `flatten_first` runs before its action (E27-S04, #898; 22 `OpenExposure`): cancel
the account's working orders, stop its algos, close its positions reduce-only; if it is still not
flat, the action is not carried out (`409 open_exposure`). E29/E39's flatten is not on `main`, so
the null adapter reports every account still not flat: nothing is destroyed, disabled or deleted.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

__all__ = ["Flattener", "NoFlatten"]


class Flattener(Protocol):
    """Flatten one account as the Owner `actor` asked, then say whether it is flat."""

    async def flatten(self, account_id: UUID, *, actor: UUID) -> bool:
        """`True` once the account holds no exposure, `False` while it still does."""


class NoFlatten:
    """The null `Flattener` until E29/E39's flatten is on `main`: nothing is flattened, nothing is
    sent, and the account is reported still not flat."""

    async def flatten(self, account_id: UUID, *, actor: UUID) -> bool:
        return False
