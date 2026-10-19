#!/usr/bin/env python3
"""GOV-005 support: idempotently apply .github/branch-protection.json to a
GitHub repository's `main` branch protection (CONSTITUTION.md C-9.1, C-10.1;
docs/plan/01-sdlc-and-branching.md §6.1, §7).

A dry run unless given --apply. Refuses a missing or unknown key (`x-` keys too:
nothing is stripped and sent), a floor crossed, a lockout, a live setting the
file does not declare (a nested one too), and, without --allow-weaken, any
change weaker than the live state. It writes no ruleset, and refuses while the
ruleset rules on the branch (a merge queue) differ from the file.

This script never runs automatically from a PR-triggered workflow (see the
break-glass runbook in CONTRIBUTING.md) — it is invoked manually by an admin
or via `workflow_dispatch` with an environment approval, using a credential
scoped to repository administration only.

Exit codes: 0 success / no-op / clean dry run, 1 desired-state validation
failed, refused or apply failed, 2 internal error (network/auth not configured).
Stdlib only (urllib), so it runs before any package manager is scaffolded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from check_required_check_reconciliation import ReconciliationError, load_workflow_job_names

DEFAULT_DESIRED_STATE_PATH = ".github/branch-protection.json"
API_BASE = "https://api.github.com"
#: The most an API answer may hold. The protection and rules answers are a few kB, so a larger
#: one is refused rather than buffered (cv-unbounded-read, #3716).
MAX_RESPONSE_BYTES = 1 << 20
#: The most load_desired_state reads, in characters; .github/branch-protection.json is ~6 kB.
MAX_FILE_CHARS = 1 << 20
GITHUB_ACTIONS_APP_ID = 15368

# Every setting the file declares, with its JSON type (a dict holds nested settings). A full PUT
# replaces the whole object, so a missing key would drop a setting.
SETTINGS: dict[str, Any] = {
    "required_status_checks": {"strict": bool, "checks": list},
    "required_pull_request_reviews": {
        "required_approving_review_count": int,
        "require_code_owner_reviews": bool,
        "dismiss_stale_reviews": bool,
        "require_last_push_approval": bool,
    },
    "enforce_admins": bool,
    "required_linear_history": bool,
    "allow_force_pushes": bool,
    "allow_deletions": bool,
    "block_creations": bool,
    "required_conversation_resolution": bool,
    "lock_branch": bool,
    "allow_fork_syncing": bool,
    "required_signatures": bool,
    "restrictions": type(None),
}
# Top-level keys the scripts read but never send or compare as settings (`merge_queue` is a
# ruleset rule, compared with the branch's rules and never written). Top-level `$` keys are notes.
# Any other key is refused.
META_KEYS = frozenset({"branch", "merge_queue", "pending_checks"})
# Compared with live, never sent: it has its own endpoint, not the protection PUT.
CHECK_ONLY_KEYS = frozenset({"required_signatures"})
# Dotted setting -> the value that protects `main` more; a change away from it weakens protection.
PROTECTIVE: dict[str, bool] = {
    "enforce_admins": True,
    "required_linear_history": True,
    "required_conversation_resolution": True,
    "block_creations": True,
    "required_signatures": True,
    "allow_force_pushes": False,
    "allow_deletions": False,
    "required_status_checks.strict": True,
    "required_pull_request_reviews.require_code_owner_reviews": True,
    "required_pull_request_reviews.dismiss_stale_reviews": True,
    "required_pull_request_reviews.require_last_push_approval": True,
}
# Review settings that need an approval from someone other than the author or last pusher. Every
# agent works as the owner's account, so with enforce_admins on no pull request could merge.
# Relax this in the PR that gives reviewers their own accounts ($deviations, C-4.1).
APPROVAL_LOCKOUTS = (
    "required_approving_review_count",
    "require_code_owner_reviews",
    "require_last_push_approval",
)


class DesiredStateError(Exception):
    """Raised when the desired-state file fails validation."""


class ApplyError(Exception):
    """Raised when the GitHub API call fails."""


class _Body(Protocol):
    def read(self, amt: int, /) -> bytes: ...


def _read_answer(response: _Body, method: str, url: str) -> bytes:
    """The answer's body, refused when it is over MAX_RESPONSE_BYTES."""
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ApplyError(f"{method} {url}: the answer is over {MAX_RESPONSE_BYTES} bytes")
    return body


@dataclass(frozen=True)
class Diff:
    added: dict
    removed: dict
    changed: dict

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def render(self) -> str:
        lines = []
        for key, value in sorted(self.added.items()):
            lines.append(f"  + {key} = {json.dumps(value)}")
        for key, value in sorted(self.removed.items()):
            lines.append(f"  - {key} = {json.dumps(value)}")
        for key, (old, new) in sorted(self.changed.items()):
            lines.append(f"  ~ {key}: {json.dumps(old)} -> {json.dumps(new)}")
        return "\n".join(lines)


def load_desired_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read(MAX_FILE_CHARS + 1)
    except FileNotFoundError as exc:
        raise DesiredStateError(f"desired-state file not found: {path}") from exc
    if len(text) > MAX_FILE_CHARS:
        raise DesiredStateError(f"desired-state file is over {MAX_FILE_CHARS} characters: {path}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DesiredStateError(f"desired-state file is not valid JSON: {exc}") from exc
    validate_desired_state(data)
    return data


def _shape_problems(obj: dict[str, Any], schema: dict[str, Any], where: str = "") -> list[str]:
    """Missing, mistyped and unknown keys (an `x-` key included: none is stripped and sent)."""
    known = set(schema) | (set() if where else META_KEYS | {k for k in obj if k[:1] == "$"})
    problems = [f"unknown key {where}{key}" for key in obj if key not in known]
    for key, kind in schema.items():
        if key not in obj:
            problems.append(f"missing {where}{key}")
        elif isinstance(kind, dict):
            value = obj[key]
            nested = _shape_problems(value, kind, f"{key}.") if isinstance(value, dict) else None
            problems += [f"{key} must be an object"] if nested is None else nested
        elif type(obj[key]) is not kind:
            problems.append(f"{where}{key} must be {kind.__name__}")
    return problems


def validate_desired_state(data: dict[str, Any]) -> None:
    """Shape, then floors no file may cross (the review settings are weakening-checked against
    live instead: see `weakening_changes`)."""
    problems = _shape_problems(data, SETTINGS)
    if problems:
        raise DesiredStateError("; ".join(problems))
    if data.get("enforce_admins") is not True:
        raise DesiredStateError(
            "enforce_admins must be true — there is no admin merge (CONSTITUTION.md C-9.1)"
        )
    if data.get("allow_force_pushes") is not False:
        raise DesiredStateError("allow_force_pushes must be false")
    if data.get("required_linear_history") is not True:
        raise DesiredStateError("required_linear_history must be true")
    if data.get("allow_deletions") is not False:
        raise DesiredStateError("allow_deletions must be false")
    if data.get("lock_branch") is not False:
        raise DesiredStateError("lock_branch must be false: a locked branch takes no merge")
    checks = data["required_status_checks"]["checks"]
    shape = {"context": str, "app_id": int}
    if not checks or any(
        not isinstance(c, dict) or _shape_problems(c, shape, "c.") for c in checks
    ):
        raise DesiredStateError("required_status_checks.checks must list {context, app_id} pairs")


def compare_view(desired: dict[str, Any]) -> dict[str, Any]:
    """The declared settings shaped like a normalised GET .../protection: no notes, no meta keys,
    checks sorted. `restrictions` is null: the file models no per-actor push restriction."""
    view = {key: value for key, value in desired.items() if key in SETTINGS}
    checks = _sorted_checks(view["required_status_checks"]["checks"])
    return {**view, "required_status_checks": {**view["required_status_checks"], "checks": checks}}


def to_api_payload(desired: dict[str, Any]) -> dict[str, Any]:
    """Exactly what the GitHub REST API's PUT .../branches/main/protection endpoint accepts."""
    return {k: v for k, v in compare_view(desired).items() if k not in CHECK_ONLY_KEYS}


def _at(state: Any, path: str) -> Any:
    for part in path.split("."):
        state = state.get(part) if isinstance(state, dict) else None
    return state


def weakening_changes(live: dict[str, Any], desired: dict[str, Any]) -> list[str]:
    """Each way `desired` protects `main` less than `live` (both shaped by compare_view)."""
    out = [
        f"{path}: {json.dumps(safe)} -> {json.dumps(_at(desired, path))}"
        for path, safe in PROTECTIVE.items()
        if _at(live, path) is safe and _at(desired, path) is not safe
    ]
    count = "required_pull_request_reviews.required_approving_review_count"
    if (_at(desired, count) or 0) < (_at(live, count) or 0):
        out.append(f"{count}: {_at(live, count)} -> {_at(desired, count)}")
    kept = _at(desired, "required_status_checks.checks") or []
    out += [
        f"required_status_checks.checks: drops {json.dumps(check)}"
        for check in _at(live, "required_status_checks.checks") or []
        if check not in kept
    ]
    if live.get("restrictions") is not None and desired.get("restrictions") is None:
        out.append("restrictions: removed")
    return out


def lockout_reasons(desired: dict[str, Any], workflows_glob: str) -> list[str]:
    """Settings that would stop every merge: a required check no pull_request workflow reports, or
    that another app than GitHub Actions must report, a merge queue whose required checks no
    merge_group workflow reports (#3433), or an approval no agent can give (APPROVAL_LOCKOUTS)."""
    events = ["pull_request", "merge_group"] if desired.get("merge_queue") else ["pull_request"]
    checks = desired["required_status_checks"]["checks"]
    reviews = desired["required_pull_request_reviews"]
    reasons = [
        f"required check '{check['context']}' must come from app {check['app_id']}, but only "
        f"GitHub Actions (app {GITHUB_ACTIONS_APP_ID}) runs .github/workflows"
        for check in checks
        if check["app_id"] != GITHUB_ACTIONS_APP_ID
    ] + [
        f"no {event} workflow reports required check '{check['context']}'"
        for event in events
        for check in checks
        if check["context"] not in load_workflow_job_names(workflows_glob, event)
    ]
    return reasons + [
        f"required_pull_request_reviews.{key} is {json.dumps(reviews[key])}: GitHub never counts "
        "an author's own approval and every agent uses the owner's account, so with "
        "enforce_admins on no pull request could merge (see $deviations)"
        for key in APPROVAL_LOCKOUTS
        if reviews[key]
    ]


def fetch_live_state(repo: str, token: str, branch: str = "main") -> dict:
    """Fetch and normalise (see `_normalise_live_state`) the live protection
    state so callers can diff it directly against a `compare_view` result."""
    url = f"{API_BASE}/repos/{repo}/branches/{branch}/protection"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return _normalise_live_state(json.loads(_read_answer(response, "GET", url)))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # No protection configured yet — treat as an empty live state.
            return {}
        raise ApplyError(f"GET {url} failed: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"GET {url} failed: {exc.reason}") from exc


# Top-level keys the GET .../protection response wraps as `{"enabled": bool}`
# (or, for `required_pull_request_reviews`/`required_status_checks`, embeds
# extra read-only fields such as `url`/`contexts_url`/`contexts`) that the PUT
# body does not accept in that shape. Mapped here so the live response can be
# normalised into the same flat shape as the desired-state payload before
# diffing — otherwise every key differs on every run and re-apply is never a
# no-op (AC4).
_BOOL_WRAPPED_KEYS = (
    "enforce_admins",
    "allow_force_pushes",
    "allow_deletions",
    "required_linear_history",
    "required_conversation_resolution",
    "lock_branch",
    "allow_fork_syncing",
    "block_creations",
    "required_signatures",
)

# Read-only fields GitHub adds to nested objects in the GET response that
# never appear in (and are rejected or ignored by) the PUT body. `contexts`
# repeats `checks` without the app that must report each one: `checks` is kept.
_NESTED_READONLY_KEYS = {"url", "contexts_url", "contexts", "users_url", "teams_url", "apps_url"}


# Top-level fields GitHub adds to the GET response that are pure metadata
# about the response itself, never part of any desired state and never
# accepted by the PUT body.
_TOP_LEVEL_READONLY_KEYS = {"url"}


def _sorted_checks(checks: list[Any]) -> list[Any]:
    return sorted(checks, key=lambda check: json.dumps(check, sort_keys=True))


def _normalise_live_state(live: dict) -> dict:
    """Reshape a raw GET .../branches/{branch}/protection response into the
    flat shape the PUT body (and this repo's desired-state file) uses, so
    `diff_state` compares like with like."""
    normalised: dict = {}
    for key, value in live.items():
        if key in _TOP_LEVEL_READONLY_KEYS:
            continue
        if key in _BOOL_WRAPPED_KEYS and isinstance(value, dict) and "enabled" in value:
            normalised[key] = value["enabled"]
        elif isinstance(value, dict):
            normalised[key] = {k: v for k, v in value.items() if k not in _NESTED_READONLY_KEYS}
        else:
            normalised[key] = value
    if normalised:  # GET omits `restrictions` when no push restriction is set
        normalised.setdefault("restrictions", None)
    if isinstance(normalised.get("required_status_checks", {}).get("checks"), list):
        rsc = normalised["required_status_checks"]
        rsc["checks"] = _sorted_checks(rsc["checks"])
    return normalised


def diff_state(live: dict, desired_payload: dict) -> Diff:
    """Shallow key-by-key diff between the (already-normalised) live state
    and the desired PUT payload. Callers reading from the real GitHub API
    MUST pass `live` through `_normalise_live_state` first — `fetch_live_state`
    does this for them; the two are kept separate only so unit tests can
    exercise the diff logic directly against hand-built flat dicts."""
    added: dict = {}
    removed: dict = {}
    changed: dict = {}
    live_keys = set(live.keys())
    desired_keys = set(desired_payload.keys())
    for key in desired_keys - live_keys:
        added[key] = desired_payload[key]
    for key in live_keys - desired_keys:
        removed[key] = live[key]
    for key in live_keys & desired_keys:
        if live[key] != desired_payload[key]:
            changed[key] = (live[key], desired_payload[key])
    return Diff(added=added, removed=removed, changed=changed)


def apply_state(repo: str, token: str, payload: dict, branch: str = "main") -> None:
    url = f"{API_BASE}/repos/{repo}/branches/{branch}/protection"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            _read_answer(response, "PUT", url)
    except urllib.error.HTTPError as exc:
        raise ApplyError(f"PUT {url} failed: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"PUT {url} failed: {exc.reason}") from exc


# --- Rules on the branch (repository rulesets) ----------------------------
#
# A merge queue is a ruleset rule, not branch protection. This script writes no ruleset: it cannot
# prove that a queue's check_response_timeout_minutes covers ci-required's run time (most lane
# jobs' timeouts read a repository variable), and a queue that times out fails every merge group.
# The owner sets the queue in the UI, and the file's `merge_queue` block must match it.


def fetch_branch_rules(repo: str, token: str, branch: str = "main") -> dict:
    """Every active ruleset rule on `branch`, as {type: parameters}; a type that more than one
    ruleset sets gets a ` #<n>` suffix, so none hides another."""
    url = f"{API_BASE}/repos/{repo}/rules/branches/{branch}?per_page=100"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            body = _read_answer(response, "GET", url)
    except urllib.error.HTTPError as exc:
        raise ApplyError(f"GET {url} failed: {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"GET {url} failed: {exc.reason}") from exc
    try:
        rules = json.loads(body)
    except ValueError as exc:
        raise ApplyError(f"GET {url}: the answer is not JSON") from exc
    if not isinstance(rules, list) or len(rules) >= 100:
        raise ApplyError(f"GET {url}: not a list of fewer than 100 rules")
    if not all(isinstance(rule, dict) for rule in rules):
        raise ApplyError(f"GET {url}: a rule that is not an object")
    view: dict = {}
    for rule in rules:
        kind = str(rule.get("type"))
        count = sum(key.split(" #")[0] == kind for key in view)
        view[f"{kind} #{count + 1}" if count else kind] = rule.get("parameters") or {}
    return view


def diff_rules(live_rules: dict, desired: dict) -> Diff:
    """The rules on the branch (`fetch_branch_rules`) against the file's: its `merge_queue`
    block, or none."""
    declared = {"merge_queue": desired["merge_queue"]} if desired.get("merge_queue") else {}
    return diff_state(live_rules, declared)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desired-state", default=DEFAULT_DESIRED_STATE_PATH)
    parser.add_argument("--workflows-glob", default=".github/workflows/*.yml")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument(
        "--token-env",
        default="GH_BRANCH_PROTECTION_TOKEN",
        help="environment variable holding the repo-administration-scoped token",
    )
    parser.add_argument("--branch", default="main")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="the default: print the diff between live and desired state; change nothing",
    )
    mode.add_argument("--apply", action="store_true", help="write the desired state")
    parser.add_argument(
        "--allow-weaken",
        action="store_true",
        help="permit changes weaker than the live state (only on an owner decision)",
    )
    args = parser.parse_args(argv)

    try:
        desired = load_desired_state(args.desired_state)
    except DesiredStateError as exc:
        print(f"apply-branch-protection: invalid desired state: {exc}", file=sys.stderr)
        return 1
    try:
        lockouts = lockout_reasons(desired, args.workflows_glob)
    except ReconciliationError as exc:
        print(f"apply-branch-protection: {exc}", file=sys.stderr)
        return 2
    for reason in lockouts:
        print(f"apply-branch-protection: refusing, lockout: {reason}", file=sys.stderr)
    if lockouts:
        return 1

    payload = compare_view(desired)

    if not args.repo:
        print("apply-branch-protection: --repo or $GITHUB_REPOSITORY required", file=sys.stderr)
        return 2
    token = os.environ.get(args.token_env)
    if not token:
        print(
            f"apply-branch-protection: token not found in ${args.token_env}",
            file=sys.stderr,
        )
        return 2

    try:
        live = fetch_live_state(args.repo, token, args.branch)
        diff = diff_state(live, payload)
        rules = diff_rules(fetch_branch_rules(args.repo, token, args.branch), desired)

        if diff.is_empty() and rules.is_empty():
            print("apply-branch-protection: no changes — live state matches desired state")
            return 0
        if not diff.is_empty():
            print("apply-branch-protection: protection diff (live -> desired):")
            print(diff.render())
        if not rules.is_empty():
            print("apply-branch-protection: rules on the branch (live -> file):")
            print(rules.render())
        refusals = [f"live has {key}, which the file does not declare" for key in diff.removed]
        if not rules.is_empty():
            refusals.append(
                "the branch's rules differ from the file, and this script writes no ruleset: set "
                "the merge queue in the UI, then declare it in merge_queue"
            )
        refusals += [  # a nested one too: the PUT replaces the whole object
            f"live has {key}.{sub}, which the file does not declare"
            for key, schema in SETTINGS.items()
            if isinstance(schema, dict) and isinstance(live.get(key), dict)
            for sub in live[key]
            if sub not in schema
        ]
        refusals += [
            f"{key} has its own endpoint" for key in CHECK_ONLY_KEYS if key in diff.changed
        ]
        if not args.allow_weaken:
            refusals += [f"weaker than live: {w}" for w in weakening_changes(live, payload)]
        for reason in refusals:
            print(f"apply-branch-protection: refusing: {reason}", file=sys.stderr)
        if refusals:
            return 1
        if not args.apply:
            print("apply-branch-protection: dry run, not applying (pass --apply)")
            return 0
        apply_state(args.repo, token, to_api_payload(desired), args.branch)
        print("apply-branch-protection: applied")
        return 0
    except ApplyError as exc:
        print(f"apply-branch-protection: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
