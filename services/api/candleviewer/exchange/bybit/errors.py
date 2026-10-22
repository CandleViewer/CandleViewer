"""Domain errors for the exchange.bybit module (M4)."""

from __future__ import annotations


class ExchangeBybitError(Exception):
    """Base exception for the M4 `exchange.bybit` module."""


class FrameTooLarge(ConnectionError):
    """A private-stream frame above the read's bound (G-8b, 24 §14.2 rule 13): the library closed
    the socket for it (1009, past `max_size`), or the read refused it whole. The socket is gone;
    the stream counts it as `oversize`, the key probe as a transport error."""
