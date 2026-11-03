"""Loopback-only target guard (BQ-08 default; C-12.9, C-13.5).

A load target must be a loopback address literal or `localhost` (the fixture backend, or a
container the test itself started and published on loopback). No DNS lookup is made, so the
guard is offline; any hostname that is not `localhost` is refused, exchange hosts by name.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

_EXCHANGE_SUFFIXES = (".bybit.com", ".bytick.com")


def assert_loopback_target(url: str) -> str:
    """Return the normalised host if `url` targets loopback, else raise `RuntimeError`."""
    host = (urlsplit(url if "//" in url else f"//{url}").hostname or "").lower()
    if not host:
        raise RuntimeError("bench target has no host")
    if host in ("bybit.com", "bytick.com") or host.endswith(_EXCHANGE_SUFFIXES):
        raise RuntimeError(f"refusing exchange host {host!r} as a bench target (C-13.5)")
    if host == "localhost":
        return host
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        raise RuntimeError(f"bench target {host!r} is not a loopback literal (C-12.9)") from None
    if not addr.is_loopback:
        raise RuntimeError(f"bench target {host!r} is not loopback (C-12.9)")
    return host
