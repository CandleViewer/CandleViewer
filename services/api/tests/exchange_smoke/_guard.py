"""Demo-only environment guard for the `exchange_smoke` suite (E08-T05).

The smoke suite is the only code under `tests/` allowed to reach the exchange. It is
opt-in (`CV_EXCHANGE_SMOKE=1`), demo-only, uses **no credentials**, and fails
closed: any live-looking configuration raises before a socket is opened
(security notes threat 2; C-2.11, C-13.5).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

#: Only these hosts may be dialled: the demo REST host and the public stream
#: demo uses (demo has no public feed of its own — public_ws.PUBLIC_WS_URLS).
# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
DEMO_REST_URL = "https://api-demo.bybit.com"
# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
DEMO_HOSTS = ("api-demo.bybit.com", "stream.bybit.com")
_OPT_IN = "CV_EXCHANGE_SMOKE"
#: Env vars that name the target environment; every one must be `demo` if set.
_ENV_VARS = ("CV_ENVIRONMENT", "CV_SMOKE_ENV", "CV_BYBIT_ENV")
#: The live and testnet REST hosts (the adapter's `ALLOWED_REST_HOSTS`, less demo's) and the
#: testnet stream: a `CV_*` value that names one aborts, whatever its shape (a list, a path, JSON).
# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
_LIVE_HOSTS = ("api.bybit.", "api.bytick.", "api-testnet.bybit.", "stream-testnet.bybit.")
#: Words that say live: read in a `CV_BYBIT*` value, and in any other `CV_*` value that is a URL.
_LIVE_WORDS = ("live", "mainnet", "prod")
_URL = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.I)
#: What a name lookup drops or reads as a dot: the code points IDNA maps to nothing (RFC 3454
#: table B.1: the soft hyphen, zero-width spaces and joiners, the word joiner, the BOM, the
#: combining grapheme joiner, Mongolian selectors and the variation selectors), and the label
#: separators IDNA reads as `.` that compatibility normalization leaves (U+3002, U+FF61).
_IGNORED: dict[int, str | None] = {
    **dict.fromkeys([0x00AD, 0x034F, 0x1806, 0x180B, 0x180C, 0x180D, 0x200B, 0x200C, 0x200D]),
    **dict.fromkeys([0x2060, 0xFEFF, *range(0xFE00, 0xFE10)]),
    0x3002: ".",
    0xFF61: ".",
}


def _folded(value: str) -> str:
    """The value as a resolver reads a host in it: NFKD (a fullwidth letter is its ASCII one;
    unlike NFKC, a combining mark never merges into the letter before it, so a live word stays
    one), without what a lookup drops, its label separators as dots, lower-cased."""
    return unicodedata.normalize("NFKD", value).translate(_IGNORED).lower()


class SmokeGuardError(RuntimeError):
    """The smoke suite refused to run against this configuration."""


def opted_in(env: Mapping[str, str]) -> bool:
    return env.get(_OPT_IN) == "1"


def assert_demo_only(env: Mapping[str, str]) -> None:
    """Raise `SmokeGuardError` unless the configuration is unambiguously demo."""
    for var in _ENV_VARS:
        value = env.get(var)
        if value is not None and value.strip().lower() != "demo":
            raise SmokeGuardError(
                f"exchange_smoke is demo-only: {var} is not 'demo' - refusing to run"
            )
    base = env.get("CV_BYBIT_REST_BASE_URL")
    if base is not None and base.rstrip("/") != DEMO_REST_URL:
        raise SmokeGuardError(
            f"exchange_smoke is demo-only: CV_BYBIT_REST_BASE_URL is not {DEMO_REST_URL}"
        )
    for key, value in env.items():
        upper = key.upper()
        if upper.startswith("CV_") and ("API_KEY" in upper or "API_SECRET" in upper) and value:
            raise SmokeGuardError(
                f"exchange_smoke uses no credentials: unset {key} before running the suite"
            )
        if not upper.startswith("CV_"):
            continue
        # The error names the variable, never its value: a URL may carry a password (#1849).
        lower = _folded(value)
        if any(host in lower for host in _LIVE_HOSTS):
            raise SmokeGuardError(f"exchange_smoke is demo-only: {key} names a live host")
        said = any(word in lower for word in _LIVE_WORDS)
        if said and (upper.startswith("CV_BYBIT") or _URL.fullmatch(value.strip())):
            raise SmokeGuardError(f"exchange_smoke is demo-only: {key} points at live")
