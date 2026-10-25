"""The bootstrap Owner's mint service (#4479 C1, SR-023) over a scripted store. The transaction
itself runs on Postgres in tests/integration/auth/test_bootstrap_owner_pg.py (CI only)."""

from __future__ import annotations

import base64
import hashlib
import inspect
import secrets
import traceback
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest

from candleviewer.auth.bootstrap_owner import (
    BOOTSTRAP_INVITE_TTL,
    BootstrapOwnerService,
    BootstrapRefusal,
    BootstrapStoreRefusal,
    BootstrapTarget,
    bootstrap_identity,
)
from candleviewer.auth.errors import BootstrapOwnerRefused
from candleviewer.auth.invite_service import INVITE_TTL, hash_token
from candleviewer.auth.models import InviteCreateRequest
from candleviewer.settings import Environment
from candleviewer.storage.repositories import bootstrap_owner_sqlalchemy as store

_NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
_EMAIL = "first.owner@x.invalid"
_TARGET = BootstrapTarget(_EMAIL, "first.owner", None)
_ROW = (uuid.UUID(int=1), uuid.UUID(int=2), True, 0)


class _Store:
    """`BootstrapOwnerStore` with scripted answers; keeps what each call was given."""

    def __init__(self, *, state: Any = None, minted: Any = _ROW) -> None:
        self.state, self.minted = state, minted
        self.reads: list[tuple[str, str]] = []
        self.mints: list[dict[str, Any]] = []

    async def bootstrap_state(self, email: str, username: str) -> Any:
        self.reads.append((email, username))
        return self.state

    async def mint_owner_invite(self, **given: Any) -> Any:
        self.mints.append(given)
        if isinstance(self.minted, Exception):
            raise self.minted
        return self.minted


def _service(store: _Store) -> BootstrapOwnerService:
    return BootstrapOwnerService(store, environment=Environment.DEMO, clock=lambda: _NOW)


async def test_mint_stores_only_the_sha256_of_a_256_bit_token() -> None:
    store = _Store()
    invite = await _service(store).mint(_TARGET)
    (given,) = store.mints
    assert len(base64.urlsafe_b64decode(invite.token + "=")) == 32  # 256 bits
    assert given["token_hash"] == hashlib.sha256(invite.token.encode()).hexdigest()
    assert [k for k, v in given.items() if invite.token in str(v)] == []  # never the token
    assert given["password_hash"].startswith("$argon2id$")  # a placeholder: nothing signs in
    assert (given["email"], given["username"]) == (_EMAIL, "first.owner")


async def test_invite_expires_after_the_bootstrap_ttl() -> None:
    store = _Store()
    invite = await _service(store).mint(_TARGET)
    assert BOOTSTRAP_INVITE_TTL == timedelta(hours=4) < INVITE_TTL  # ruling 6, not the 72 h
    expected = _NOW + timedelta(hours=4)
    assert (store.mints[0]["now"], store.mints[0]["expires_at"]) == (_NOW, expected)
    assert (invite.user_id, invite.invite_id, invite.expires_at) == (*_ROW[:2], expected)
    assert (invite.created_user, invite.superseded) == (True, 0)


@pytest.mark.parametrize(
    ("email", "identity"),
    [
        ("ops@x.invalid", ("ops@x.invalid", "ops")),  # 3 characters, the shortest username
        (f"{'a' * 32}@x.invalid", (f"{'a' * 32}@x.invalid", "a" * 32)),  # 32, the longest
        ("First.O_w-9@x.invalid", ("First.O_w-9@x.invalid", "First.O_w-9")),  # every kind
        ("op@x.invalid", None),  # 2 characters
        (f"{'a' * 33}@x.invalid", None),  # 33 characters
        ("o+tag@x.invalid", None),  # `+` is no username character
        ("ópé@x.invalid", None),  # nor is a letter outside ASCII
        ("ops x@x.invalid", None),  # whitespace
        ("ops@localhost", None),  # `POST /users` wants a dot in the domain
        ("ops", None),
        ("", None),
    ],
)
def test_identity_takes_the_username_from_the_email(
    email: str, identity: tuple[str, str] | None
) -> None:
    assert bootstrap_identity(email) == identity


def test_invite_request_keeps_its_username_and_email_rules() -> None:
    """The hoisted `Username`/`Email` aliases change nothing in `POST /users` (its schema at
    #4479 B, 15c6da70)."""
    fields = InviteCreateRequest.model_json_schema()["properties"]
    username = {"maxLength": 32, "minLength": 3, "pattern": "^[a-zA-Z0-9._-]+$"}
    email = {"maxLength": 254, "minLength": 3, "pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"}
    assert fields["username"] == username | {"title": "Username", "type": "string"}
    assert fields["email"] == email | {"title": "Email", "type": "string"}


@pytest.mark.parametrize("state", [None, uuid.UUID(int=7)])
async def test_check_names_the_user_to_create_or_reuse(state: uuid.UUID | None) -> None:
    store = _Store(state=state)
    assert await _service(store).check(_EMAIL) == BootstrapTarget(_EMAIL, "first.owner", state)
    assert store.reads == [(_EMAIL, "first.owner")]


async def test_check_refuses_an_unusable_email_before_the_store() -> None:
    store = _Store()
    assert await _service(store).check("o+tag@x.invalid") is BootstrapRefusal.NOT_CANDIDATE
    assert store.reads == []


@pytest.mark.parametrize("refusal", list(BootstrapRefusal))
async def test_check_returns_refusals_and_mint_raises_them(refusal: BootstrapRefusal) -> None:
    store = _Store(state=refusal.value, minted=refusal.value)
    assert await _service(store).check(_EMAIL) is refusal  # returned: a step's answer
    with pytest.raises(BootstrapOwnerRefused) as refused:
        await _service(store).mint(_TARGET)
    assert refused.value.reason is refusal


@pytest.mark.parametrize(
    "target",
    [
        BootstrapTarget("ops x@x.invalid", "ops x", None),  # whitespace
        BootstrapTarget("ópé@x.invalid", "ópé", None),  # letters outside ASCII
        BootstrapTarget("ops@b", "ops", None),  # `a@b`: no dot in the domain
        BootstrapTarget(_EMAIL, "someone.else", None),  # not the email's username
    ],
)
async def test_mint_refuses_a_target_check_would_not_build(
    target: BootstrapTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mint applies `POST /users`' rules again, before it draws a token or calls the store:
    a target built outside `check` never names the first Owner."""
    drawn: list[int] = []

    def draw(nbytes: int) -> str:
        drawn.append(nbytes)
        return "t" * 43

    monkeypatch.setattr(secrets, "token_urlsafe", draw)
    store = _Store()
    with pytest.raises(BootstrapOwnerRefused) as refused:
        await _service(store).mint(target)
    assert (refused.value.reason, store.mints, drawn) == (BootstrapRefusal.NOT_CANDIDATE, [], [])


async def test_token_is_in_no_repr_or_message() -> None:
    invite = await _service(_Store()).mint(_TARGET)
    shown = repr(invite) + str(invite)
    assert invite.token not in shown and hash_token(invite.token) not in shown
    assert _EMAIL not in repr(_TARGET) and "first.owner" not in repr(_TARGET)
    here = inspect.currentframe()  # this test's own frame heads each traceback: skip it
    for answer in ("owner_exists", RuntimeError("store down")):
        store = _Store(minted=answer)
        with pytest.raises((BootstrapOwnerRefused, RuntimeError)) as failed:
            await _service(store).mint(_TARGET)
        stored = store.mints[0]["token_hash"]
        frames = [f for f, _ in traceback.walk_tb(failed.tb) if f is not here]
        assert "BootstrapOwnerService.mint" in {f.f_code.co_qualname for f in frames}
        held = [v for f in frames for v in f.f_locals.values() if isinstance(v, str)]
        assert [v for v in held if hash_token(v) == stored] == []  # no frame keeps the token
        message = str(failed.value) + repr(failed.value)
        assert stored not in message and _EMAIL not in message


def test_refusal_values_match_the_store() -> None:
    """DC-4479-18: `storage` may not import `auth`, so the store spells the refusals itself."""
    values = {refusal.value for refusal in BootstrapRefusal}
    assert values == {store.OWNER_EXISTS, store.NOT_CANDIDATE}
    assert values == set(get_args(store.BootstrapStoreRefusal))
    assert values == set(get_args(BootstrapStoreRefusal))
