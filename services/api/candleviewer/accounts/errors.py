"""Domain errors for the accounts module (M13)."""

from __future__ import annotations


class AccountsError(Exception):
    """Base exception for the M13 `accounts` module."""


class WithdrawPermissionError(AccountsError, ValueError):
    """Key grants a withdraw or transfer right (C-2.8, SR-030a); problem code
    `key_withdraw_permission`."""


class AccountNotFoundError(AccountsError):
    """Missing, soft-deleted, foreign, revoked-hidden or path-mismatched: all identical, so
    there is no existence oracle; problem code `not_found`."""

    def __init__(self, entity: str) -> None:
        super().__init__("not found")
        self.entity = entity


class AccountScopeDeniedError(AccountsError):
    """Caller lacks the live owner role; uniform `forbidden`."""


class AccountConflictError(AccountsError):
    """Uniqueness or state conflict; problem code `conflict`."""

    def __init__(self, constraint: str) -> None:
        super().__init__(constraint)
        self.constraint = constraint


class AccountRuleError(AccountsError):
    """Data-rule violation; problem code `validation_failed`."""

    def __init__(self, rule: str) -> None:
        super().__init__(rule)
        self.rule = rule


class AccountVersionConflictError(AccountsError):
    """If-Match token is stale; problem code `precondition_failed`."""
