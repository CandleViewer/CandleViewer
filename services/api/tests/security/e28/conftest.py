"""E28-X03 (#976): the live-target guard and the suite's one world per module.

The guard (the ticket's Security notes) aborts the whole run, at collection and again before
each module, when the target is live: this suite never runs against a live UID. It lives here,
not in a helper module, because it names the venue's deny-listed hosts (C-13.5), which only a
conftest or a test module may spell (`cv-adapter-isolation`, C-2.2). It reads the names of the
exchange-key variables, never a value, and the values of the environment switches and host
lists, which hold no secret. A target is live when:

- `CV_ENVIRONMENT` or `CV_FEED` is `live`, or live trading (`CV_TRADING_LIVE_ENABLED`) is on;
- any `CV_BYBIT_API_*` variable is set: the cells use no key, so one configured points the run at
  an account it must not touch (synthetic, non-functional keys only, and here none at all);
- a host list or venue address the run may reach (`CV_CI_ALLOWED_HOSTS`, any `CV_*_HOST*`,
  `CV_*_URL*` or `CV_*_BASE*`) names a host of C-13.5's deny list, `*.bybit.com` or `*.bytick.com`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final

import pytest
from dotenv import dotenv_values

from candleviewer.statechart.bindings import b16_session
from tests.security.e28._world import E28World, e28_world

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


def target_env() -> dict[str, str]:
    """What the app's `Settings` reads: a `.env` at the working directory (`env_file`), with the
    process environment over it. The guard judges both; it names a variable, never a value."""
    dotenv = {k: v for k, v in dotenv_values(Path.cwd() / ".env").items() if v is not None}
    return {**dotenv, **os.environ}


def _abort_if_live() -> None:
    if (why := live_target_refusal(target_env())) is not None:
        pytest.exit(f"E28-X03 security suite refused to run: {why}", returncode=4)


_abort_if_live()  # at collection, before any module of this suite is imported


@pytest.fixture(scope="module", autouse=True)
def _live_guard() -> None:
    """Again before each module: a variable set since collection aborts the run as well."""
    _abort_if_live()


@pytest.fixture(scope="module")
def _e28(_live_guard: None) -> Iterator[E28World]:
    with e28_world() as world:
        yield world


@pytest.fixture
def world(_e28: E28World, b16_audit: object) -> E28World:
    """The module's world, reset: the stores as seeded and an empty audit log."""
    _e28.reset()
    b16_session.set_audit_sink(_e28.writes.world.audit)
    return _e28
