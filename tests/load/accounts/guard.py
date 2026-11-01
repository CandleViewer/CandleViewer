"""E27-Q03 (#892): the load-target guard for the account harness (BQ-11).

BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).

An allow-list: a base URL is accepted only when it is loopback or the compose service name `api`.
Exchange hosts (C-13.5 deny list) are named first so the refusal says why. Stdlib only, no network:
the guard parses text and never resolves a name. The k6 scripts carry the same rule in
`k6/accounts/lib/guard.js`; `test_e27_harness_guards.py` pins that the two agree on a table.
"""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import urlsplit

ALLOWED_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1", "api"})
# nosemgrep: cv-adapter-isolation reason=deny-table owner=@CandleViewer/security review=2027-03-25
_EXCHANGE: Final = re.compile(r"(^|\.)(bybit|bytick)\.com$", re.IGNORECASE)


class TargetRefused(ValueError):
    """A fixed message; it never echoes the URL (it could carry a credential in its userinfo)."""


def check_target(base_url: str) -> str:
    """The base URL without a trailing slash, or `TargetRefused`."""
    try:
        parts = urlsplit(base_url)
        host = parts.hostname or ""
        _ = parts.port  # a bad port raises ValueError here
    except ValueError:
        raise TargetRefused("the target URL is not valid") from None
    if _EXCHANGE.search(host):
        raise TargetRefused("an exchange host is never a load target (C-13.5)")
    if parts.scheme != "http" or parts.username or parts.password or parts.path.strip("/"):
        raise TargetRefused("the target must be a plain http base URL with no credentials or path")
    if host not in ALLOWED_HOSTS:
        raise TargetRefused("the target must be loopback or the compose service `api`")
    return base_url.rstrip("/")
