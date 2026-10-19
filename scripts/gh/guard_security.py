"""Guard 3 -- Security-close guard (E01-T07 AC3).

- On `opened`/`labeled`: auto-apply the `security` label when an
  always-security `area/*` label is present (`02-definition-of-ready-done.md`
  section 8), so it cannot be omitted at creation.
- On `closed`, for any issue carrying `security` (explicit or always-security
  area): require a comment carrying an explicit sign-off marker
  (`Security sign-off: pass`) from someone who independently holds repo
  write access.

CandleViewer is a single-owner, user-level repo (`CandleViewer/CandleViewer`,
ADR-0017 Q1) -- there is no GitHub organization and so no
`@CandleViewer/security` team whose membership can be queried
(`GET /orgs/{org}/teams/{team}/...` always 404s: the org does not exist).
Per the ticket's "Agent-delivery adaptations", the security-engineer sign-off
role is represented as an actor-attributed comment from a verified
repo-write-access holder (`gh_adapter.has_write_access`) carrying the
explicit marker -- any comment at all from such a holder is *not* sufficient
(a routine "LGTM" or status update must never silently satisfy this gate).
"""

from __future__ import annotations

from scripts.gh.issue_body import SECURITY_SIGNOFF_MARKER_RE
from scripts.gh.models import Comment, Decision, Issue

GUARD_NAME = "security-guard"
DOD_REF = "02-definition-of-ready-done.md#8"

# `02-definition-of-ready-done.md` section 8: "always" security areas.
ALWAYS_SECURITY_AREAS = frozenset(
    {
        "area/auth-rbac",
        "area/oms-execution",
    }
)

SECURITY_LABEL = "security"


def _is_always_security(issue: Issue) -> bool:
    return bool(issue.labels & ALWAYS_SECURITY_AREAS)


def evaluate_label_sync(issue: Issue) -> Decision:
    """Run on `opened`/`labeled`: auto-apply `security` for always-security areas."""
    if SECURITY_LABEL in issue.labels:
        return Decision(
            allow=True,
            reason="security label already present",
            dod_ref=DOD_REF,
            audit_note="security-guard: label already present",
            guard=GUARD_NAME,
        )

    if not _is_always_security(issue):
        return Decision(
            allow=True,
            reason="no always-security area label present",
            dod_ref=DOD_REF,
            audit_note="security-guard: no-op (not an always-security area)",
            guard=GUARD_NAME,
        )

    return Decision(
        allow=True,
        reason="always-security area label present without explicit security label",
        dod_ref=DOD_REF,
        audit_note="security-guard: auto-applying 'security' label",
        guard=GUARD_NAME,
        add_labels=frozenset({SECURITY_LABEL}),
    )


def _signoff_comment(comments: list[Comment], closer_login: str = "") -> Comment | None:
    for comment in comments:
        if not comment.author_has_write_access:
            continue
        if not closer_login or comment.author_login == closer_login:
            # Fail closed: unknown closer → no comment can be trusted as independent.
            # Separation of duties: the closer cannot self-sign-off (C-10.1).
            continue
        match = SECURITY_SIGNOFF_MARKER_RE.search(comment.body)
        if match and match.group(1).lower() == "pass":
            return comment
    return None


def evaluate_close(
    issue: Issue,
    comments: list[Comment],
    *,
    write_access_lookup_failed: bool = False,
) -> Decision:
    """Run on `closed`: require an explicit security sign-off comment from a
    verified repo-write-access holder when the ticket is (explicitly or
    implicitly) security-labelled."""
    if not (SECURITY_LABEL in issue.labels or _is_always_security(issue)):
        return Decision(
            allow=True,
            reason="ticket is not security-labelled and touches no always-security area",
            dod_ref=DOD_REF,
            audit_note="security-guard: not applicable",
            guard=GUARD_NAME,
        )

    if write_access_lookup_failed:
        return Decision(
            allow=False,
            reason="could not verify commenter repo write access (API error)",
            dod_ref=DOD_REF,
            audit_note="security-guard: BLOCKED - guard could not verify, must be re-run",
            guard=GUARD_NAME,
            fail_closed=True,
        )

    signoff = _signoff_comment(comments, issue.actor_login)
    if signoff is not None:
        return Decision(
            allow=True,
            reason=f"security sign-off comment found from @{signoff.author_login}",
            dod_ref=DOD_REF,
            audit_note=f"security-guard: ALLOWED - sign-off by @{signoff.author_login}",
            guard=GUARD_NAME,
        )

    if any(
        c.write_access_check_failed and SECURITY_SIGNOFF_MARKER_RE.search(c.body)
        for c in comments
    ):
        # A sign-off marker exists but we could not verify the commenter's
        # write access -- fail closed rather than silently drop the claim.
        return Decision(
            allow=False,
            reason="could not verify commenter's repo write access for security sign-off (API error)",
            dod_ref=DOD_REF,
            audit_note="security-guard: BLOCKED - guard could not verify comment author, must be re-run",
            guard=GUARD_NAME,
            fail_closed=True,
        )

    return Decision(
        allow=False,
        reason="no explicit 'Security sign-off: pass' comment from a repo-write-access holder",
        dod_ref=DOD_REF,
        audit_note=(
            f"security-guard: BLOCKED - missing DoD item 'Security sign-off' (see {DOD_REF})"
        ),
        guard=GUARD_NAME,
    )
