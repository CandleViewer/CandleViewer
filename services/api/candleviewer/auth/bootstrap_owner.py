"""Bootstrap-Owner mint port and service (#4479 C1, SR-023): the first Owner of a fresh database.

The offline CLI (#4479 C2) runs `check()` as a gate step, then `mint()` after its host, KEK and
phrase checks. The mint is ONE transaction behind `BootstrapOwnerStore` (M10's
`bootstrap_owner_sqlalchemy.py`): a role-less `invited` user (F1) and one marked, single-use
`owner` invite valid `BOOTSTRAP_INVITE_TTL`, while no Owner is active. The 256-bit token reaches
the store only as its sha256; `BootstrapInvite` keeps it for the CLI's single print, and no repr
shows it or the email. cv-api never builds this service or its store (R4, S8).
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import TypeAdapter, ValidationError

from candleviewer.auth.errors import BootstrapOwnerRefused
from candleviewer.auth.invite_service import hash_token, placeholder_password_hash
from candleviewer.auth.models import Email, Username
from candleviewer.settings import Environment

#: Ruling 6 (#4479): an Owner bearer token on the tailnet lives 4 h, not `INVITE_TTL`'s 72 h.
BOOTSTRAP_INVITE_TTL = timedelta(hours=4)


class BootstrapRefusal(StrEnum):
    OWNER_EXISTS = "owner_exists"  # an active Owner exists: never a second bootstrap
    NOT_CANDIDATE = "not_candidate"  # not a role-less `invited` user, or its username is taken


#: The store's refusals, each a `BootstrapRefusal` value; `storage` types its own copy
#: (DC-4479-18).
BootstrapStoreRefusal = Literal["owner_exists", "not_candidate"]


class BootstrapOwnerStore(Protocol):
    async def bootstrap_state(
        self, email: str, username: str
    ) -> uuid.UUID | BootstrapStoreRefusal | None:
        """Read only: a refusal, the id of the `invited` user the email names, or None when no
        user has it and the username is free (the mint creates the user)."""
        ...

    async def mint_owner_invite(
        self,
        *,
        email: str,
        username: str,
        password_hash: str,
        token_hash: str,
        expires_at: datetime,
        now: datetime,
    ) -> tuple[uuid.UUID, uuid.UUID, bool, int] | BootstrapStoreRefusal:
        """One transaction under the bootstrap lock. Returns (user id, invite id, user created,
        invites superseded) after its commit, or a refusal after rolling back."""
        ...


@dataclass(frozen=True, slots=True)
class BootstrapTarget:
    """Whom `check` found; `user_id` None means the mint creates the user, and the mint decides
    again under its lock. The mint refuses one `check` could not have built. PII: no repr."""

    email: str = field(repr=False)
    username: str = field(repr=False)
    user_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class BootstrapInvite:
    """A committed mint. `token` is the raw one-time token, for the CLI's single print only."""

    user_id: uuid.UUID
    invite_id: uuid.UUID
    expires_at: datetime
    created_user: bool
    superseded: int
    token: str = field(repr=False)


_EMAIL: TypeAdapter[str] = TypeAdapter(Email)
_USERNAME: TypeAdapter[str] = TypeAdapter(Username)


def bootstrap_identity(email: str) -> tuple[str, str] | None:
    """`(email, username)`, the username being the part before `@`, both under `POST /users`'
    rules (`InviteCreateRequest`); None when either fails. Nothing of the value is raised."""
    try:
        address = _EMAIL.validate_python(email)
        return address, _USERNAME.validate_python(address.split("@", 1)[0])
    except ValidationError:
        return None


class BootstrapOwnerService:
    """`environment` is the configured one, so no caller can choose `live` (arch P9)."""

    def __init__(
        self,
        store: BootstrapOwnerStore,
        *,
        environment: Environment,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._environment = environment
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def environment(self) -> Environment:
        """The configured environment: the CLI flow takes `live` from here."""
        return self._environment

    async def check(self, email: str) -> BootstrapTarget | BootstrapRefusal:
        """Read only, so it returns its refusal (a gate step's answer); an email `POST /users`
        would refuse is `not_candidate` before any statement."""
        identity = bootstrap_identity(email)
        if identity is None:
            return BootstrapRefusal.NOT_CANDIDATE
        state = await self._store.bootstrap_state(*identity)
        if isinstance(state, str):
            return BootstrapRefusal(state)
        return BootstrapTarget(*identity, state)

    async def mint(self, target: BootstrapTarget) -> BootstrapInvite:
        """Raises `BootstrapOwnerRefused` when the store refuses: nothing was written. A target
        `check` could not have built (`POST /users`' rules) is refused before a token is drawn.
        No frame of a refused or failed mint keeps the token."""
        if bootstrap_identity(target.email) != (target.email, target.username):
            raise BootstrapOwnerRefused(BootstrapRefusal.NOT_CANDIDATE)
        now = self._clock()
        token = secrets.token_urlsafe(32)
        expires_at = now + BOOTSTRAP_INVITE_TTL
        try:
            outcome = await self._store.mint_owner_invite(
                email=target.email,
                username=target.username,
                password_hash=placeholder_password_hash(),
                token_hash=hash_token(token),
                expires_at=expires_at,
                now=now,
            )
            if isinstance(outcome, str):
                raise BootstrapOwnerRefused(BootstrapRefusal(outcome))
        except BaseException:
            del token  # a traceback keeps this frame, never the token in it
            raise
        user_id, invite_id, created_user, superseded = outcome
        return BootstrapInvite(user_id, invite_id, expires_at, created_user, superseded, token)
