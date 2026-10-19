"""Guard 2 -- QA sign-off (E01-T07 AC1/AC2/AC4).

CandleViewer is a single-owner, user-level repo (`CandleViewer/CandleViewer`,
ADR-0017 Q1) -- there is no GitHub organization and so no `@CandleViewer/qa`
team whose membership can be queried (`GET /orgs/{org}/teams/{team}/...`
always 404s: the org does not exist). Per the ticket's "Agent-delivery
adaptations", role sign-offs are represented as an **actor-attributed
comment from someone who independently holds repo write access** (verified
via `gh_adapter.has_write_access`, a real, always-available collaborator-
permission check -- no PAT/App/org required) carrying the documented marker
(`QA sign-off: pass`), OR an explicitly recorded QA-capacity-deviation
statement by the ticket owner (permitted by
`docs/plan/02-definition-of-ready-done.md` section 3.2 / section 8).

A forged marker typed into the *issue body* by the author never satisfies
this guard -- only an actor-attributed *comment* from someone with verified
write access, or the owner's own deviation comment, counts. Being the
ticket's *author* is not itself a credential (anyone can open an issue and
comment as its author), so `issue.owner_login` alone can never be trusted to
grant a QA-skip -- both the sign-off and the deviation path require the
`author_has_write_access` check.
"""

from __future__ import annotations

from scripts.gh.issue_body import QA_DEVIATION_MARKER_RE, QA_SIGNOFF_MARKER_RE
from scripts.gh.models import Comment, Decision, Issue

GUARD_NAME = "qa-guard"
DOD_REF = "02-definition-of-ready-done.md#3.2"

GATED_KINDS = {"Story", "Bug"}
# An issue with no type/* label at all (`gh_adapter._kind_from_labels`
# returns "Unlabeled") must not silently skip this guard just because it
# doesn't map to a known Kind -- that would let an unlabelled Story/Bug
# close without QA sign-off. Gate it the same as Story/Bug.
GATED_KINDS_INCLUDING_UNKNOWN = GATED_KINDS | {"Unlabeled"}


def _qa_signoff_comment(comments: list[Comment], closer_login: str = "") -> Comment | None:
    for comment in comments:
        if not comment.author_has_write_access:
            continue
        if not closer_login or comment.author_login == closer_login:
            # Fail closed: unknown closer → no comment can be trusted as independent.
            # Separation of duties: the actor who closed the issue cannot
            # supply its own sign-off (independent review, C-10.1).
            continue
        match = QA_SIGNOFF_MARKER_RE.search(comment.body)
        if match and match.group(1).lower() == "pass":
            return comment
    return None


def _deviation_comment(comments: list[Comment], owner_login: str) -> Comment | None:
    for comment in comments:
        if comment.author_login != owner_login:
            continue
        if not comment.author_has_write_access:
            # Anyone can open an issue and comment as its author; being
            # `owner_login` is not a credential. Only trust the deviation
            # path when the commenter independently verified as holding
            # repo write access.
            continue
        if QA_DEVIATION_MARKER_RE.search(comment.body):
            return comment
    return None


def evaluate(
    issue: Issue,
    comments: list[Comment],
    *,
    write_access_lookup_failed: bool = False,
) -> Decision:
    if issue.kind not in GATED_KINDS_INCLUDING_UNKNOWN:
        return Decision(
            allow=True,
            reason=f"Kind={issue.kind} is not Story/Bug; QA sign-off guard does not apply",
            dod_ref=DOD_REF,
            audit_note="qa-guard: not applicable",
            guard=GUARD_NAME,
        )

    if write_access_lookup_failed:
        # Fail-closed: an API error while checking repo write access must
        # never be treated as an implicit pass.
        return Decision(
            allow=False,
            reason="could not verify commenter repo write access (API error)",
            dod_ref=DOD_REF,
            audit_note="qa-guard: BLOCKED - guard could not verify, must be re-run",
            guard=GUARD_NAME,
            fail_closed=True,
        )

    signoff = _qa_signoff_comment(comments, issue.actor_login)
    if signoff is not None:
        return Decision(
            allow=True,
            reason=f"QA sign-off found in comment by @{signoff.author_login}",
            dod_ref=DOD_REF,
            audit_note=f"qa-guard: ALLOWED - sign-off by @{signoff.author_login}",
            guard=GUARD_NAME,
        )

    deviation = _deviation_comment(comments, issue.owner_login)
    if deviation is not None:
        return Decision(
            allow=True,
            reason="QA capacity deviation recorded by ticket owner",
            dod_ref=DOD_REF,
            audit_note=(
                f"qa-guard: ALLOWED - QA capacity deviation path used "
                f"(recorded by @{deviation.author_login})"
            ),
            guard=GUARD_NAME,
        )

    if any(
        c.write_access_check_failed
        and (c.author_login == issue.owner_login or QA_SIGNOFF_MARKER_RE.search(c.body))
        and (QA_DEVIATION_MARKER_RE.search(c.body) or QA_SIGNOFF_MARKER_RE.search(c.body))
        for c in comments
    ):
        # A sign-off or deviation marker exists but we could not verify the
        # commenter's write access -- fail closed rather than silently drop
        # the claim.
        return Decision(
            allow=False,
            reason="could not verify commenter's repo write access for QA sign-off/deviation (API error)",
            dod_ref=DOD_REF,
            audit_note="qa-guard: BLOCKED - guard could not verify comment author, must be re-run",
            guard=GUARD_NAME,
            fail_closed=True,
        )

    return Decision(
        allow=False,
        reason=(
            "no actor-attributed QA sign-off comment from a repo-write-access holder and no "
            "recorded QA capacity deviation by the ticket owner"
        ),
        dod_ref=DOD_REF,
        audit_note=(
            "qa-guard: BLOCKED - missing DoD item 'QA sign-off' "
            f"(see {DOD_REF})"
        ),
        guard=GUARD_NAME,
    )
