"""Thin GitHub-side-effects adapter for board-automation guards (E01-T07).

Every mutating call here goes through `gh` (the GitHub CLI, already
authenticated in Actions via `GH_TOKEN`) so this module has no direct HTTP
dependency and stays easy to stub in tests. Nothing in here interprets issue
body/comment content as anything other than data: content is always passed
via files or argv/environment, never interpolated into a shell string that
mixes trusted and untrusted text.

Reading/writing the Projects v2 `Kind` single-select field requires the
`PROJECTS_PAT` fine-grained PAT (ADR-0017; project-scoped, not the default
`GITHUB_TOKEN`, which has no Projects v2 GraphQL access at all). `gh`
transparently uses whatever token is exported as `GH_TOKEN`/`GITHUB_TOKEN` in
the environment for a given call; callers that need Projects v2 access must
ensure `PROJECTS_PAT` is exported as `GH_TOKEN` for the duration of that call
(see `run_guard.py`'s `_projects_env` context manager).
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from scripts.gh.issue_body import gov_bot_marker
from scripts.gh.models import Comment, Decision, Issue

GOV_LOG_PREFIX = "GOV-006"

# CandleViewer's organisation-level Projects v2 board, CandleViewer/projects/3 (an organisation
# project since 2026-10-19). The ADR-0017 Q1/Q4 evidence was gathered on the former user project.
PROJECT_OWNER = "CandleViewer"
PROJECT_NUMBER = 3
KIND_FIELD_NAME = "Kind"


class GhApiError(RuntimeError):
    """Raised when a `gh` invocation fails; callers must treat this as a
    fail-closed condition, never a silent pass."""


class GhNotFoundError(GhApiError):
    """Raised specifically for a 404 from the GitHub API -- distinct from
    other failures so callers can tell "resource does not exist" (a valid,
    expected outcome for e.g. "is this login a team member") apart from a
    genuine API/network/auth failure that must fail closed."""


def _run_gh(args: list[str], *, input_text: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["gh", *args],
            input=input_text,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").lower()
        if "http 404" in stderr or "404 not found" in stderr or "not found (http 404)" in stderr:
            raise GhNotFoundError(f"gh {' '.join(args)} failed: {exc}") from exc
        raise GhApiError(f"gh {' '.join(args)} failed: {exc}") from exc
    except FileNotFoundError as exc:
        raise GhApiError(f"gh {' '.join(args)} failed: {exc}") from exc
    return result.stdout


def fetch_issue(repo: str, number: int) -> tuple[Issue, list[Comment]]:
    """Fetch the current issue state via `gh issue view --json`."""
    raw = _run_gh(
        [
            "issue",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "number,body,labels,author,comments",
        ]
    )
    data = json.loads(raw)
    labels = frozenset(lbl["name"] for lbl in data.get("labels", []))
    kind = _kind_from_labels(labels)
    comments = [
        Comment(
            author_login=c["author"]["login"],
            body=c.get("body", ""),
        )
        for c in data.get("comments", [])
    ]
    issue = Issue(
        number=data["number"],
        kind=kind,
        labels=labels,
        body=data.get("body", "") or "",
        owner_login=data.get("author", {}).get("login", ""),
    )
    return issue, comments


@dataclass(frozen=True)
class ProjectItemKind:
    """The Projects v2 item id plus its current `Kind` single-select value
    (or `None` if the field is unset), needed to reconcile against the
    `type/*` label (ADR-0017 Q1/Q4). Requires `PROJECTS_PAT` -- the default
    `GITHUB_TOKEN` has no Projects v2 GraphQL access at all."""

    item_id: str
    field_id: str
    option_id_by_kind: dict[str, str]
    current_kind: str | None


_PROJECT_ITEM_KIND_QUERY = """
query($owner: String!, $number: Int!, $issueNumber: Int!, $repoOwner: String!, $repoName: String!) {
  organization(login: $owner) {
    projectV2(number: $number) {
      field(name: "Kind") {
        ... on ProjectV2SingleSelectField {
          id
          options { id name }
        }
      }
      items(first: 100) {
        nodes {
          id
          content { ... on Issue { number repository { owner { login } name } } }
          fieldValueByName(name: "Kind") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}
"""


def get_project_item_kind(
    repo: str, number: int, *, project_owner: str = PROJECT_OWNER, project_number: int = PROJECT_NUMBER
) -> ProjectItemKind | None:
    """Read the Projects v2 `Kind` field for the item backing this issue.

    Returns `None` if the issue is not on the board at all. Raises
    `GhApiError` on any GraphQL/auth failure (e.g. `PROJECTS_PAT` missing,
    expired, or lacking project access) -- callers must fail closed, not
    silently skip reconciliation."""
    owner, repo_name = repo.split("/", 1)
    raw = _run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={_PROJECT_ITEM_KIND_QUERY}",
            "-f",
            f"owner={project_owner}",
            "-F",
            f"number={project_number}",
            "-F",
            f"issueNumber={number}",
            "-f",
            f"repoOwner={owner}",
            "-f",
            f"repoName={repo_name}",
        ]
    )
    data = json.loads(raw)
    project = data.get("data", {}).get("organization", {}).get("projectV2")
    if project is None:
        return None
    field = project.get("field") or {}
    field_id = field.get("id")
    option_id_by_kind = {opt["name"]: opt["id"] for opt in field.get("options", [])}
    for item in project.get("items", {}).get("nodes", []):
        content = item.get("content") or {}
        if content.get("number") != number:
            continue
        content_repo = content.get("repository") or {}
        if content_repo.get("owner", {}).get("login") != owner or content_repo.get("name") != repo_name:
            continue
        current = (item.get("fieldValueByName") or {}).get("name")
        return ProjectItemKind(
            item_id=item["id"],
            field_id=field_id,
            option_id_by_kind=option_id_by_kind,
            current_kind=current,
        )
    return None


_SET_PROJECT_FIELD_MUTATION = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
    value: { singleSelectOptionId: $optionId }
  }) {
    projectV2Item { id }
  }
}
"""


def set_project_item_kind(
    project_id: str, item_id: str, field_id: str, option_id: str
) -> None:
    """Write the Projects v2 `Kind` single-select field. Requires
    `PROJECTS_PAT`; raises `GhApiError` on failure (fail closed -- callers
    must not treat a write failure as "already in sync")."""
    _run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={_SET_PROJECT_FIELD_MUTATION}",
            "-f",
            f"projectId={project_id}",
            "-f",
            f"itemId={item_id}",
            "-f",
            f"fieldId={field_id}",
            "-f",
            f"optionId={option_id}",
        ]
    )


_PROJECT_ID_QUERY = """
query($owner: String!, $number: Int!) {
  organization(login: $owner) { projectV2(number: $number) { id } }
}
"""


def get_project_id(project_owner: str = PROJECT_OWNER, project_number: int = PROJECT_NUMBER) -> str:
    raw = _run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={_PROJECT_ID_QUERY}",
            "-f",
            f"owner={project_owner}",
            "-F",
            f"number={project_number}",
        ]
    )
    data = json.loads(raw)
    return data["data"]["organization"]["projectV2"]["id"]


@contextmanager
def _pat_env(var_name: str) -> Iterator[bool]:
    """Swap `GH_TOKEN`/`GITHUB_TOKEN` for the PAT in env var ``var_name`` for
    the duration of the block. Yields `True` if it was present, `False` if
    absent (callers must then skip whatever this PAT gates, never silently
    proceed on the default `GITHUB_TOKEN`, which lacks the scope)."""
    pat = os.environ.get(var_name, "")
    if not pat:
        yield False
        return
    prior_gh_token = os.environ.get("GH_TOKEN")
    prior_github_token = os.environ.get("GITHUB_TOKEN")
    os.environ["GH_TOKEN"] = pat
    os.environ["GITHUB_TOKEN"] = pat
    try:
        yield True
    finally:
        if prior_gh_token is None:
            os.environ.pop("GH_TOKEN", None)
        else:
            os.environ["GH_TOKEN"] = prior_gh_token
        if prior_github_token is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = prior_github_token


def projects_pat_env():
    """Swap in `PROJECTS_PAT` (ADR-0017: Projects: Read and write,
    account-scoped) for Projects v2 GraphQL calls -- the default
    `GITHUB_TOKEN` has no Projects v2 access at all."""
    return _pat_env("PROJECTS_PAT")


_LABEL_TO_KIND = {
    "type/epic": "Epic",
    "type/story": "Story",
    "type/task": "Task",
    "type/bug": "Bug",
    "type/spike": "Spike",
    "type/chore": "Chore",
}


def _kind_from_labels(labels: frozenset[str]) -> str:
    for label in labels:
        if label in _LABEL_TO_KIND:
            return _LABEL_TO_KIND[label]
    # No type/* label at all: this must never silently default to a
    # non-gated Kind like "Task" -- an unlabelled Story/Bug would then skip
    # the QA sign-off guard entirely (fail open). Surface it as its own
    # explicit "Unlabeled" kind so gated guards can treat "we don't know"
    # conservatively (see guard_qa_signoff.GATED_KINDS).
    return "Unlabeled"


def has_write_access(repo: str, login: str) -> bool:
    """Check whether ``login`` independently holds push/write (or higher)
    access to ``repo``, via the collaborator-permission API. Used by
    `guard_qa_signoff` to verify a QA-capacity-deviation comment is really
    from someone with repo authority, not merely "the issue's author"
    (which anyone can be, by opening the issue themselves).

    Raises `GhApiError` on any failure other than a `404` (which means "not
    a collaborator at all", i.e. no access) -- callers must fail closed on
    that -- an API failure must never be silently treated as "no access"."""
    try:
        raw = _run_gh(
            [
                "api",
                f"repos/{repo}/collaborators/{login}/permission",
            ]
        )
    except GhNotFoundError:
        return False
    data = json.loads(raw)
    permission = data.get("permission", "")
    return permission in ("admin", "maintain", "write")


def reopen_issue(repo: str, number: int) -> None:
    _run_gh(["issue", "reopen", str(number), "--repo", repo])


def add_labels(repo: str, number: int, labels: frozenset[str]) -> None:
    if not labels:
        return
    _run_gh(["issue", "edit", str(number), "--repo", repo, "--add-label", ",".join(sorted(labels))])


@dataclass(frozen=True)
class ExistingComment:
    comment_id: str
    body: str


def _find_own_comment(repo: str, number: int, guard: str) -> ExistingComment | None:
    marker = gov_bot_marker(guard)
    raw = _run_gh(
        ["issue", "view", str(number), "--repo", repo, "--json", "comments"]
    )
    data = json.loads(raw)
    for c in data.get("comments", []):
        if marker in c.get("body", ""):
            return ExistingComment(comment_id=c["id"], body=c["body"])
    return None


def post_or_update_decision_comment(repo: str, number: int, decision: Decision) -> None:
    """Post exactly one audit comment per guard, editing the prior one on
    re-run instead of spamming a new comment each time.

    Edits target the specific comment id this guard previously found and
    posted (via `gh api ... PATCH` on that comment), never `--edit-last`:
    `--edit-last` unconditionally targets whatever comment is chronologically
    last on the issue, which may belong to a *different* guard if several run
    against the same close event -- that would silently overwrite another
    guard's audit trail instead of this guard's own."""
    marker = gov_bot_marker(decision.guard)
    verdict = "ALLOWED" if decision.allow else "BLOCKED"
    body = (
        f"{marker}\n"
        f"**Board automation: {decision.guard}** -- {verdict}\n\n"
        f"{decision.audit_note}\n\n"
        f"Reason: {decision.reason}\n\n"
        f"DoD reference: {decision.dod_ref}\n"
    )
    existing = _find_own_comment(repo, number, decision.guard)
    if existing is not None:
        _run_gh(
            [
                "api",
                f"repos/{repo}/issues/comments/{existing.comment_id}",
                "-X",
                "PATCH",
                "-f",
                f"body={body}",
            ],
        )
    else:
        _run_gh(
            ["issue", "comment", str(number), "--repo", repo, "--body-file", "-"],
            input_text=body,
        )


def log_decision(number: int, decision: Decision) -> None:
    """Structured workflow log line, per the ticket's Observability section."""
    print(f"{GOV_LOG_PREFIX} {number} {decision.guard} "
          f"{'ALLOWED' if decision.allow else 'BLOCKED'} {decision.reason}")
