"""Domain errors for the accounts module (M13)."""

from __future__ import annotations


class AccountsError(Exception):
    """Base exception for the M13 `accounts` module."""


class WithdrawPermissionError(AccountsError, ValueError):
    """Key reports Withdraw permission; problem code `key_withdraw_permission` (C-2.8)."""
