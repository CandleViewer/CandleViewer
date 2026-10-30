"""E28-X03 (#976): the live-target guard (the ticket's Security notes: the suite must never run
against a live UID). It reads the names of the exchange-key variables, never a value, and the
values of the environment switches and host lists, which hold no secret. A target is live when:

- `CV_ENVIRONMENT` or `CV_FEED` is `live`, or live trading (`CV_TRADING_LIVE_ENABLED`) is on;
- any `CV_BYBIT_API_*` variable is set: the cells use no key, so one configured points the run at
  an account it must not touch (synthetic, non-functional keys only, and here none at all);
- a host list or venue address the run may reach (`CV_CI_ALLOWED_HOSTS`, any `CV_*_HOST*`,
  `CV_*_URL*` or `CV_*_BASE*`) names a host of C-13.5's deny list, `*.bybit.com` or `*.bytick.com`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

_KEYS: Final = "CV_BYBIT_API_"
_ON: Final = frozenset({"true", "1", "yes", "on"})
_SWITCHES: Final = {"CV_ENVIRONMENT": {"live"}, "CV_FEED": {"live"}, "CV_TRADING_LIVE_ENABLED": _ON}
_HOST_LISTS: Final = re.compile(r"^CV_(CI_ALLOWED_HOSTS|\w*_(HOSTS?|URLS?|BASE)(_\w+)?)$")
_DENIED: Final = re.compile(r"(^|[^a-z0-9-])([a-z0-9-]+\.)*(bybit|bytick)\.com($|[^a-z0-9.-])")


def live_target_refusal(env: Mapping[str, str]) -> str | None:
    """Why the suite may not run against `env`, or None. Names a variable, never a value."""
    for name, live in _SWITCHES.items():
        if env.get(name, "").strip().lower() in live:
            return f"{name} targets live"
    if any(name.upper().startswith(_KEYS) for name in env):
        return f"a {_KEYS}* variable is set: the suite runs with no exchange key"
    for name, value in sorted(env.items()):
        if _HOST_LISTS.match(name.upper()) and _DENIED.search(value.lower()):
            return f"{name} names a live venue host (C-13.5's deny list)"
    return None
