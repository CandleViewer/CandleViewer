"""Domain errors for the accounts module (M13)."""

from __future__ import annotations


class AccountsError(Exception):
    """Base exception for the M13 `accounts` module."""


class WithdrawPermissionError(AccountsError, ValueError):
    """Key grants a withdraw or transfer right (C-2.8, SR-030a); problem code
    `key_withdraw_permission`."""
