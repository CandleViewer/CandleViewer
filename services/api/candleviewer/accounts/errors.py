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


class AccountUnchangedError(AccountsError):
    """A compare-and-set on the account's enabled flag missed: a concurrent disable or re-enable
    stored it first, and nothing was written. The caller's request is then a repeat (#898)."""


class KeyDestroyFailedError(AccountsError):
    """A key of the account could not be destroyed (M2 refused or failed it), so the delete or the
    revoke stopped there and nothing later ran; problem code `store_unavailable` (503), and a retry
    destroys what is left (#898). Never carries M2's text."""


class ProfileUnavailableError(AccountsError):
    """A profile could not be read. The effective read (the order path's cache) raises it when the
    store failed or timed out, when writes kept overtaking the read, or for an unreadable stored
    row (`invalid_row`), and the order path fails closed on it (SR-E28-24), never using a default.
    The REST reads (`read_profiles`, `read_profile`, #906) raise it for an unreadable row, answered
    503 `store_unavailable`."""


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
