"""Unit (E42-T05 #966 BK-10): `DownloadLinks`. A 256-bit token of which only the SHA-256 is kept,
compared in constant time against every link; one spend however many callers race; 5 minutes on
the server clock; `LinkUnknown` (404) for another backup's or user's token, `LinkGone` (410) for
the caller's own spent or expired one; the bounds and the retention horizon (SR-3456-01)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from candleviewer.admin.backups.links import (
    ENDED_KEPT,
    ENDED_LINKS_MAX,
    LINK_TTL,
    LIVE_LINKS_MAX,
    Consumed,
    DownloadLink,
    DownloadLinks,
    LinkGone,
    LinksFull,
    LinkSpent,
    LinkUnknown,
)

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
OWNER, OTHER, SESSION, B1, B2 = (UUID(int=n) for n in (1, 2, 101, 11, 12))
_TICK = timedelta(microseconds=1)


class Clock:
    now = T0

    def __call__(self) -> datetime:
        return self.now


def _issue(store: DownloadLinks) -> tuple[str, DownloadLink]:
    return store.issue(user_id=OWNER, session_id=SESSION, backup_id=B1)


def _fetch(store: DownloadLinks, token: str, user: UUID | None = OWNER, b: UUID = B1) -> Consumed:
    return store.consume(token, backup_id=b, user_id=user)


def test_token_is_43_urlsafe_characters_from_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    store = DownloadLinks()
    tokens = {_issue(store)[0] for _ in range(8)}
    assert len(tokens) == 8 and all(re.fullmatch(r"[A-Za-z0-9_-]{43}", t) for t in tokens)
    monkeypatch.setattr(secrets, "token_urlsafe", lambda nbytes: f"drawn-{nbytes}")
    assert _issue(store)[0] == "drawn-32"  # 256 bits from the CSPRNG


def test_only_the_hash_is_stored() -> None:
    store = DownloadLinks()
    token, link = _issue(store)
    digest = hashlib.sha256(token.encode()).digest()
    assert store._held == {link.link_id: (digest, link)}
    assert token not in repr(vars(store)) and token not in repr(link)
    assert digest.hex() not in repr(link) and not hasattr(link, "token")
    assert (link.user_id, link.session_id, link.backup_id) == (OWNER, SESSION, B1)


async def test_consume_is_single_use_under_concurrency() -> None:
    store = DownloadLinks()
    token, link = _issue(store)

    async def fetch(user: UUID | None) -> Consumed:
        await asyncio.sleep(0)  # every caller is scheduled before any consumes
        return _fetch(store, token, user)

    results = await asyncio.gather(*(fetch(None if n % 2 else OWNER) for n in range(20)))
    spent = [r for r in results if isinstance(r, LinkSpent)]
    assert len(spent) == 1 and spent[0].link.link_id == link.link_id
    assert sum(isinstance(r, LinkGone) for r in results) == 19


def test_expiry_is_five_minutes_on_the_server_clock() -> None:
    clock = Clock()
    store = DownloadLinks(now=clock)
    (first, link), (second, _) = _issue(store), _issue(store)
    assert LINK_TTL == timedelta(minutes=5)
    assert (link.issued_at, link.expires_at) == (T0, T0 + timedelta(minutes=5))
    clock.now = T0 + LINK_TTL - _TICK
    assert isinstance(_fetch(store, first), LinkSpent)
    clock.now = T0 + LINK_TTL
    gone = _fetch(store, second)
    assert isinstance(gone, LinkGone) and gone.link.spent_at is None  # expired, never spent


def test_another_users_or_backups_token_is_unknown_and_not_spent() -> None:
    store = DownloadLinks(now=Clock())
    token, _ = _issue(store)
    for user, backup in ((OWNER, B2), (None, B2), (OTHER, B1)):
        assert _fetch(store, token, user, backup) == LinkUnknown()
    assert _fetch(store, "A" * 43) == LinkUnknown()  # a token never issued
    spent = _fetch(store, token, None)  # no bearer: the token alone names its user
    assert isinstance(spent, LinkSpent) and (spent.link.spent_at, spent.link.user_id) == (T0, OWNER)
    # Spent, it is still 404 to another user and under another backup, and 410 to its own.
    for user, backup in ((OWNER, B2), (OTHER, B1)):
        assert _fetch(store, token, user, backup) == LinkUnknown()
    assert [type(_fetch(store, token, user)) for user in (OWNER, None)] == [LinkGone, LinkGone]


def test_every_held_hash_is_compared_in_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    store = DownloadLinks()
    tokens = [_issue(store)[0] for _ in range(3)]
    compared: list[bytes] = []
    compare = hmac.compare_digest

    def spy(held: bytes, presented: bytes) -> bool:
        compared.append(presented)
        return compare(held, presented)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    assert isinstance(_fetch(store, tokens[0]), LinkSpent)  # the first held
    assert compared == [hashlib.sha256(tokens[0].encode()).digest()] * 3  # no early exit


def test_store_is_bounded() -> None:
    assert (LIVE_LINKS_MAX, ENDED_LINKS_MAX) == (1024, 1024)
    defaults = DownloadLinks()
    assert (defaults._live_max, defaults._ended_max) == (LIVE_LINKS_MAX, ENDED_LINKS_MAX)
    clock = Clock()
    store = DownloadLinks(now=clock, live_max=3, ended_max=2)
    issued = [_issue(store)[0] for _ in range(3)]
    with pytest.raises(LinksFull):
        _issue(store)
    assert len(store._held) == 3  # nothing was minted
    assert all(isinstance(_fetch(store, token), LinkSpent) for token in issued)
    _issue(store)  # spent links are not live: the oldest is forgotten, two are kept
    assert len(store._held) == 3 and _fetch(store, issued[0]) == LinkUnknown()
    assert all(isinstance(_fetch(store, token), LinkGone) for token in issued[1:])
    clock.now = T0 + LINK_TTL  # expired links are not live either
    assert [_issue(store) for _ in range(3)] and len(store._held) == 5


@pytest.mark.parametrize("spent_after", [timedelta(minutes=1), None], ids=["spent", "unspent"])
def test_an_ended_link_is_gone_for_an_hour_then_unknown(spent_after: timedelta | None) -> None:
    """SR-3456-01: an hour from the spend, even past the expiry (a spent token presented again is
    the fetch's `link_reused`), or from the expiry of a link never spent; then forgotten."""
    assert ENDED_KEPT == timedelta(hours=1)
    clock = Clock()
    store = DownloadLinks(now=clock)
    token, _ = _issue(store)
    if spent_after is not None:
        clock.now = T0 + spent_after
        assert isinstance(_fetch(store, token), LinkSpent)
    ended = clock.now if spent_after is not None else T0 + LINK_TTL
    clock.now = ended + ENDED_KEPT - _TICK
    gone = _fetch(store, token)
    assert isinstance(gone, LinkGone) and gone.link.spent_at == (spent_after and ended)
    clock.now = ended + ENDED_KEPT
    assert _fetch(store, token) == LinkUnknown() and store._held == {}


def test_a_discarded_link_is_unknown_and_frees_its_place() -> None:
    store = DownloadLinks(live_max=1)
    token, link = _issue(store)
    store.discard(link.link_id)
    store.discard(link.link_id)  # once is enough; again is nothing
    assert _fetch(store, token) == LinkUnknown()
    _issue(store)
