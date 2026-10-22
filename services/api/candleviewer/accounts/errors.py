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
    """If-Match token is stale; problem code `version_conflict` (412)."""


class ProfileUnavailableError(AccountsError):
    """The effective profile could not be read: the store failed or timed out, or writes kept
    overtaking the read. The order path fails closed on it (SR-E28-24), never using a default."""


class TradeGroupKeyReuseError(AccountsError):
    """The caller's `Idempotency-Key` already anchors a trade group with another request
    fingerprint (G-6(b), SR-E29-07), and nothing was written; problem code
    `idempotency_key_reuse` (409). Names no value: not the key, the fingerprint or the group."""


class TradeGroupStaleError(AccountsError):
    """A compare-and-set on a trade group's or a leg's status missed: the row no longer holds the
    expected status, and nothing was written."""


class ProfileChangedError(AccountsError):
    """A leg's profile is missing, soft-deleted or no longer at the version the leg was sized
    from (SR-E28-15), and nothing was written; problem code `profile_changed`, which the first
    route that raises it registers (E29-T04, with E28-T02 and E34-S02)."""
