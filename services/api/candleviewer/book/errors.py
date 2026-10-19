"""Domain errors for the book module (M7)."""

from __future__ import annotations


class BookError(Exception):
    """Base exception for the M7 `book` module."""


class BookPayloadError(BookError):
    """A snapshot/delta failed validation (non-finite, negative, oversized)."""


class BookInvariantError(BookError):
    """Applying a delta broke a book invariant (crossed, unbounded, grid)."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind
