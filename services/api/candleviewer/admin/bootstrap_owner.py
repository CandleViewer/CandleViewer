"""Offline bootstrap of the first Owner: the CLI flow (#4479 C2, SR-023; threat model U46, U49,
U50). `admin.breakglass_wiring` composes its ports; `python -m candleviewer.bootstrap_owner` runs
it (`docs/ops/runbooks/auth-rbac.md` section 4).

It runs on break-glass's host gate, `HostGatedFlow`, as it is, so its checks come in the gate's
order. It brings only its target (any string, validated after the attempt record, so a malformed
email is recorded and refused, never echoed: DC-4479-10), the line above the phrase, the mint
(C1, after the gate's last probe) and the summary. The token lives only in `_token`: the summary
prints it once, after `auth.bootstrap_owner_invited` has landed, and withholds it if that record
failed (exit 6; the next run revokes the invite). It is cleared once shown and in `run`'s
`finally`, and never reaches a record, a log line, a verdict or an exception.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from enum import IntEnum
from typing import Any, Final

import structlog

from candleviewer.admin.audited import audit_exempt, audited
from candleviewer.admin.breakglass import (
    AuditTrail,
    GateRecords,
    GateSpec,
    HostGatedFlow,
    Terminal,
    Verdict,
)
from candleviewer.audit.journal import BOOTSTRAP_ACTOR  # every record's `actor_label`: no user acts
from candleviewer.auth.bootstrap_owner import (
    BOOTSTRAP_INVITE_TTL,
    BootstrapOwnerService,
    BootstrapRefusal,
    BootstrapTarget,
    bootstrap_identity,
)
from candleviewer.auth.errors import BootstrapOwnerRefused
from candleviewer.secrets import KekCheckResult

#: The journal admits only these (`audit.journal.BOOTSTRAP_OWNER_ACTIONS`; a test pins them).
ATTEMPT: Final = "auth.bootstrap_owner_attempt"
REFUSED: Final = "auth.bootstrap_owner_refused"
INVITED: Final = "auth.bootstrap_owner_invited"
_TTL_HOURS: Final = int(BOOTSTRAP_INVITE_TTL / timedelta(hours=1))


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class BootstrapOwnerExit(IntEnum):
    """The CLI's exit status: 0 only after an invite whose records were all written, its token
    printed once. The gate's statuses keep their numbers (`GATE_STATUSES`) and 10, 14 and 15 are
    not used, so a number means one thing in both offline CLIs. Its lower-case name is the closing
    record's `reason` (the mint's `BootstrapRefusal` values keep their spelling)."""

    INVITED = 0
    STEP_FAILED = 1  # a check broke (a port raised or timed out); nothing was minted
    MINT_FAILED = 3  # rolled back, or unknown if cut at COMMIT (2 is argparse's usage)
    HOST_FS_UNAVAILABLE = 4
    API_RUNNING = 5
    AUDIT_UNAVAILABLE = 6  # a record failed; after a mint, its token is withheld
    LIVE_FLAG_REQUIRED = 7
    LIVE_FLAG_MISMATCH = 8
    KEK_UNPROVEN = 9
    NO_TTY = 11
    CONFIRMATION_MISMATCH = 12
    CONFIRMATION_TIMEOUT = 13
    OPERATOR_CANCELLED = 16  # cancelled before the mint began; carried by `RunCancelled`
    OWNER_EXISTS = 17  # an Owner is active, at the target check or inside the mint
    NOT_CANDIDATE = 18  # not a usable email, or its user cannot become the Owner

    @property
    @audit_exempt("read")
    def reason(self) -> str:
        return self.name.lower()


_X = BootstrapOwnerExit
#: The refusals of the target check and of the mint; none of them can map onto `INVITED`.
_REFUSED_BY_MINT: Final = {
    refusal.value: BootstrapOwnerExit[refusal.name] for refusal in BootstrapRefusal
}


@dataclasses.dataclass(frozen=True, slots=True)
class BootstrapOwnerPorts:
    """Everything the flow touches, composed offline; none of it is a switch (C-4.14)."""

    #: The host journal under the run lock; raises `BreakGlassUnavailable` if it cannot.
    open_journal: Callable[[], Awaitable[AuditTrail]]
    #: Straight to `audit_log` (scenario S3), or None while Postgres is unreachable.
    open_direct: Callable[[], Awaitable[AuditTrail | None]]
    #: `secrets.prove_kek_possession`: metadata only, never enrols (decision O1).
    prove_kek: Callable[[], Awaitable[KekCheckResult]]
    #: True while another session of the CLI's database role is connected (R2c).
    api_running: Callable[[], Awaitable[bool]]
    #: The check and the mint (C1), built with the configured environment: the one source of
    #: `live`.
    bootstrap: BootstrapOwnerService
    terminal: Terminal
    new_run_id: Callable[[], uuid.UUID] = uuid.uuid4


_BOOTSTRAP = GateSpec(
    "bootstrap_owner", BOOTSTRAP_ACTOR, ATTEMPT, REFUSED, INVITED, "bootstrap", BootstrapOwnerExit,
    "INVITED", "MINT_FAILED",
)  # fmt: skip


class BootstrapOwnerFlow(HostGatedFlow[BootstrapTarget]):
    """One bootstrap run per `run()`. The environment is the bootstrap service's, the configured
    one (arch P9): the one source of `live`, which `--live` only has to confirm."""

    _ports: BootstrapOwnerPorts  # the gate's ports and the bootstrap service

    def __init__(self, ports: BootstrapOwnerPorts) -> None:
        super().__init__(ports, _BOOTSTRAP, ports.bootstrap.environment)
        self._token: str | None = None  # the minted token, until the summary shows it

    @audited(ATTEMPT, REFUSED, INVITED)
    async def run(self, owner: str, *, live_flag: bool) -> BootstrapOwnerExit:
        """Mint the bootstrap invite that makes `owner` (an email, as typed) the first Owner;
        `live_flag` is `--live`. Returns the exit status; the token reaches only the terminal,
        once. A cancel is recorded and summarised first, then re-raised as `RunCancelled`."""
        try:
            return _X(await self._run(owner, live_flag=live_flag))
        finally:
            self._token = None  # however the run ended, no token outlives it

    async def _target(self, records: GateRecords, email: str) -> Verdict | BootstrapTarget:
        if bootstrap_identity(email) is None:  # recorded, never echoed, refused (DC-4479-10)
            return Verdict(_X.NOT_CANDIDATE)
        found = await self._step("target_check", lambda: self._ports.bootstrap.check(email))
        if isinstance(found, BootstrapRefusal):  # an active Owner, or not a candidate
            return Verdict(_REFUSED_BY_MINT[found])
        records.target = found.user_id  # None until the mint creates the user
        return found

    def _warning(self, email: str) -> str:
        env = self._environment.value
        return (
            f"Bootstrap mints one single-use invite that makes {email} the Owner of {env}; "
            f"it is valid {_TTL_HOURS} h."
        )

    async def _act(self, records: GateRecords, target: BootstrapTarget) -> Verdict:
        refused = await self._probe_again()  # the gate's last probe, right before the mint (R2c)
        if refused is not None:
            return refused
        # No timer and no cancel cuts it: either would leave the outcome unknown if it hit
        # COMMIT. Each statement is bounded by the relational repository's `statement_timeout`.
        try:
            invite = await records.to_the_end(self._ports.bootstrap.mint(target), "mint")
        except BootstrapOwnerRefused as exc:  # rolled back: an Owner, or the user, came first
            return Verdict(_REFUSED_BY_MINT[exc.reason])
        except Exception as exc:  # rolled back, or unknown if the link broke at COMMIT
            error = type(exc).__name__
            _log().error("bootstrap_owner.mint_failed", run_id=str(records.run_id), error=error)
            return Verdict(_X.MINT_FAILED, {"error": error, "outcome": "rolled_back_or_unknown"})
        records.target, self._token = invite.user_id, invite.token
        minted = {"invite_id": str(invite.invite_id), "expires_at": invite.expires_at.isoformat()}
        counts = {"created_user": invite.created_user, "superseded": invite.superseded}
        return Verdict(_X.INVITED, minted | counts)

    def _outcome(self, verdict: Verdict, email: str, why: str) -> list[str]:
        token, self._token = self._token, None  # shown at most once, then dropped
        env = self._environment.value
        if verdict.status is _X.INVITED:
            if verdict.unrecorded or token is None:  # its record is not durable: withheld
                return [
                    f"Bootstrap invite minted for {email} on {env}, but its record could not be "
                    "written, so its token is withheld. Run it again: the new run revokes it."
                ]
            expires = (verdict.details or {})["expires_at"]
            return [
                f"Bootstrap invite minted for {email} on {env}, valid until {expires}. Give it "
                "to the Owner once, over a channel that keeps no copy, to redeem at once.",
                f"Invite token (shown once): {token}",
            ]
        if verdict.status is _X.MINT_FAILED:  # a link lost at COMMIT may still have minted it
            return [
                f"Bootstrap mint failed ({why}); no invite is confirmed. Run it again: a new run "
                "revokes any invite this one minted."
            ]
        return [f"Bootstrap ended without an invite ({why}); nothing was minted."]
