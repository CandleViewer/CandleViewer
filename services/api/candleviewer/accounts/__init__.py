"""accounts module (M13).

Exchange accounts, API-key metadata and key rotations (E27-T01, #834 / #2495).

Public interface only — internal implementation modules are not re-exported.
Allowed dependencies (CONSTITUTION.md C-3.1): M1, M10.

- `AccountsRepository`: the domain facade over M10's driver-free `AccountsStore` port. SR-051
  scoping is applied in SQL by the store, never filtered here (C-12.4).
- Domain models carry no envelope column (C-3.2); key material stays in M2 (`secrets`).
- Domain errors map one-to-one to problem codes; every "no row" outcome is the same
  `AccountNotFoundError`, so nothing is an existence oracle.
- `AccountsService`: the lifecycle contract (`start` / `stop` / `health`).
"""

from __future__ import annotations

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
    AccountVersionConflictError,
    WithdrawPermissionError,
)
from candleviewer.accounts.models import (
    AccountKind,
    ApiKeyMetadata,
    ApiKeyRotation,
    ExchangeAccount,
    ExchangeEnv,
    KeyStatus,
    PermissionSet,
    PermissionSnapshot,
)
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.service import AccountsService

__all__: list[str] = [
    "AccountConflictError",
    "AccountKind",
    "AccountNotFoundError",
    "AccountRuleError",
    "AccountScopeDeniedError",
    "AccountVersionConflictError",
    "AccountsError",
    "AccountsRepository",
    "AccountsService",
    "ApiKeyMetadata",
    "ApiKeyRotation",
    "ExchangeAccount",
    "ExchangeEnv",
    "KeyStatus",
    "PermissionSet",
    "PermissionSnapshot",
    "WithdrawPermissionError",
]
