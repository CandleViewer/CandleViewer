"""CLI entry point for board-automation workflows (E01-T07).

Invoked from `.github/workflows/board-automation.yml` jobs. Reads the
triggering event context from environment variables (never inline
interpolation of untrusted issue content into shell), calls the appropriate
pure `evaluate()` guard, then applies (or, in observe-only mode, merely logs)
the resulting decision via the thin `gh_adapter`.

Usage:
    python -m scripts.gh.run_guard kind-sync
    python -m scripts.gh.run_guard qa-guard
    python -m scripts.gh.run_guard security-guard --mode label-sync
    python -m scripts.gh.run_guard security-guard --mode close
    python -m scripts.gh.run_guard a11y-guard

Required env vars: GH_REPO ("owner/name"), ISSUE_NUMBER, ACTOR_LOGIN.
Optional: GOVERNANCE_ENFORCE ("true"/"false", default "false" == observe-only).

CandleViewer is a single-owner, user-level repo (`CandleViewer/CandleViewer`,
ADR-0017 Q1) -- there is no GitHub organization, so `qa-guard` and
`security-guard` never query org-team membership (that endpoint 404s
unconditionally for a nonexistent org). Both instead verify, per comment,
that its author independently holds repo write access via the
collaborator-permission API (`gh_adapter.has_write_access`) -- available
under the default `GITHUB_TOKEN`, no PAT required -- and require an explicit
sign-off marker in the comment body (see `guard_qa_signoff`/`guard_security`).
"""

from __future__ import annotations

import argparse
import os
import sys

from scripts.gh import (
    gh_adapter,
    guard_a11y,
    guard_kind_sync,
    guard_qa_signoff,
    guard_security,
)
from scripts.gh.models import Decision, Issue


def _enforcing() -> bool:
    return os.environ.get("GOVERNANCE_ENFORCE", "false").strip().lower() == "true"


def _with_actor(issue: Issue) -> Issue:
    from dataclasses import replace

    return replace(issue, actor_login=os.environ.get("ACTOR_LOGIN", ""))


def _annotate_write_access(comments, repo: str) -> tuple[list, bool]:
    """Per-comment repo-write-access check, used by both `qa-guard` and
    `security-guard` (see module docstring: no org/team exists to check
    membership of instead). A lookup failure is recorded per-comment
    (`write_access_check_failed`) *and* surfaced via the second return value
    so callers that need "did any check fail at all" (as opposed to "did the
    check fail for the specific comment carrying a marker", which the guards
    themselves inspect) can also fail closed."""
    from dataclasses import replace

    annotated = []
    any_failure = False
    for c in comments:
        try:
            has_access = gh_adapter.has_write_access(repo, c.author_login)
            failed = False
        except gh_adapter.GhApiError:
            has_access = False
            failed = True
            any_failure = True
        annotated.append(replace(c, author_has_write_access=has_access, write_access_check_failed=failed))
    return annotated, any_failure


def _apply_decision(repo: str, number: int, decision: Decision) -> None:
    gh_adapter.log_decision(number, decision)
    enforcing = _enforcing()
    if decision.add_labels:
        if enforcing:
            gh_adapter.add_labels(repo, number, decision.add_labels)
        else:
            print(f"GOV-006 {number} {decision.guard} OBSERVE-ONLY would-add-labels={sorted(decision.add_labels)}")
    if decision.set_project_kind is not None:
        if enforcing:
            _write_project_kind(repo, number, decision.set_project_kind)
        else:
            print(
                f"GOV-006 {number} {decision.guard} OBSERVE-ONLY "
                f"would-set-project-kind={decision.set_project_kind!r}"
            )
    if not decision.allow:
        if enforcing:
            gh_adapter.reopen_issue(repo, number)
            gh_adapter.post_or_update_decision_comment(repo, number, decision)
        else:
            print(f"GOV-006 {number} {decision.guard} OBSERVE-ONLY would-block: {decision.reason}")
    else:
        if enforcing:
            gh_adapter.post_or_update_decision_comment(repo, number, decision)


def _write_project_kind(repo: str, number: int, kind: str) -> None:
    with gh_adapter.projects_pat_env() as available:
        if not available:
            print(f"GOV-006 {number} kind-sync SKIPPED-WRITE: PROJECTS_PAT not set")
            return
        item = gh_adapter.get_project_item_kind(repo, number)
        if item is None:
            print(f"GOV-006 {number} kind-sync SKIPPED-WRITE: issue not on the board")
            return
        option_id = item.option_id_by_kind.get(kind)
        if option_id is None:
            print(f"GOV-006 {number} kind-sync SKIPPED-WRITE: no Kind option for {kind!r}")
            return
        project_id = gh_adapter.get_project_id()
        gh_adapter.set_project_item_kind(project_id, item.item_id, item.field_id, option_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("guard", choices=["kind-sync", "qa-guard", "security-guard", "a11y-guard"])
    parser.add_argument("--mode", choices=["label-sync", "close"], default="close")
    args = parser.parse_args(argv)

    repo = os.environ["GH_REPO"]
    number = int(os.environ["ISSUE_NUMBER"])
    owner, name = repo.split("/", 1)

    issue, comments = gh_adapter.fetch_issue(repo, number)
    issue = _with_actor(issue)

    if args.guard == "kind-sync":
        with gh_adapter.projects_pat_env() as available:
            item = gh_adapter.get_project_item_kind(repo, number) if available else None
        decision = guard_kind_sync.evaluate(
            issue,
            project_kind=item.current_kind if item is not None else None,
            project_available=item is not None,
        )
    elif args.guard == "qa-guard":
        annotated, failed = _annotate_write_access(comments, repo)
        decision = guard_qa_signoff.evaluate(issue, annotated, write_access_lookup_failed=failed)
    elif args.guard == "security-guard":
        if args.mode == "label-sync":
            decision = guard_security.evaluate_label_sync(issue)
        else:
            annotated, failed = _annotate_write_access(comments, repo)
            decision = guard_security.evaluate_close(issue, annotated, write_access_lookup_failed=failed)
    else:  # a11y-guard
        decision = guard_a11y.evaluate(issue, comments, repo_owner=owner, repo_name=name)

    _apply_decision(repo, number, decision)
    return 0 if decision.allow or not _enforcing() else 1


if __name__ == "__main__":
    sys.exit(main())
