#!/usr/bin/env python3
"""`security-review-label` (#2892): label a PR that touches a C-10.2 path `security-review`.

CONSTITUTION C-10.2 says the label is applied automatically when a PR touches a security path; this
is that rule. It lists the PR's changed files through the GitHub API (a rename by its old and its
new path), prints each one a rule below matches, and adds the label when one matched and the label
is missing. It never removes a label. It is the `security-review-label` job of
.github/workflows/pr.yml, a `ci-required` lane on every PR: one job adds and judges, because a label
added with GITHUB_TOKEN starts no other workflow run.

The rules follow C-10.2 verbatim (scripts/tests/test_security_review_label.py parses the clause):
- its backend prefixes in its own spelling, `services/api/<module>/`, and in the real package,
  `services/api/candleviewer/<module>/` (the gap #2708 closed in CODEOWNERS);
- anything under `infra/`; CI workflow files: `.github/workflows/`, `.github/actions/` and GATE,
  this rule's own code, so a PR that narrows the rule is labelled by main's copy of it;
- authentication/session code in apps/web: WEB_AUTH_PATHS, and any `auth`, `session` or `sessions`
  directory under apps/web/src/, so a new slice counts before the list names it;
- dependency manifests in any directory: MANIFESTS (package and lock files, and the pnpm and npm
  configs and hooks that set overrides, install scripts and the registry), pip's
  `requirements*.txt`, and POSTINSTALL, the packages whose install scripts CI runs (SR-138);
- a path with `key`, `secret`, `token` or `crypt` in any case in a file or directory name (`*key*`
  and the rest, matched as CODEOWNERS matches a slash-less glob; camelCase TS names count).
  Verbatim, so the keymap and the design tokens match too.
SECURITY_PATH_RE joins the rules into one POSIX ERE (`--print-regex`) for a merge guard to reuse.

Exit 0: no security path; the label is on the PR or was added now; a merge group (no PR).
Exit 1 (CI-GATE-004), failing closed: a security path is touched and the label cannot be added; the
changed files cannot all be read (an API error, a short list, more than the API's 3000 files) and
the label is not on the PR; or the event or the PR number is not one this script knows.

Trust model (SR-132): the only pr.yml job with a write permission, so it checks out `main`, never
the PR, and runs this file from it with `python3 -I`: a PR cannot change the rule that judges it.
Under `pull_request` the workflow YAML itself is still the PR's; the C-10.2 workflow review covers
that. Stdlib only.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import urllib.request
from typing import Any, Protocol

LABEL = "security-review"
MAX_FILES = 3000  # GET /pulls/{n}/files lists at most this many
PAGE = 100
MODULES = ("secrets", "auth", "audit", "exchange", "oms", "risk", "admin")
WEB_AUTH_PATHS = (
    "apps/web/src/features/auth/",  # login, password change, the auth REST client
    "apps/web/src/features/invites/",  # invite redemption: password and TOTP enrolment
    "apps/web/src/lib/auth/",  # the session claims cache
    "apps/web/src/lib/http/csrfFetch.ts",  # CSRF double submit, the session cookie's re-issue
    "apps/web/src/lib/ws/core/connection.ts",  # the WS `auth` and re-`auth`, the token's lifetime
    "apps/web/src/lib/ws/policy/closePolicy.ts",  # 4401: drop the refused token, refresh first
    "apps/web/src/lib/ws/protocol/frames.ts",  # the `auth` frame: the token's one way onto the wire
    "apps/web/src/routes/guards.ts",  # requireAuth -> requireRole -> requireStepUp
    "apps/web/src/routes/manifest.ts",  # each route's access: public, roles, step-up
    "apps/web/src/routes/rbac.ts",  # the roles and the RouteAccess shape the guards read
    "apps/web/src/routes/StepUpGate.tsx",  # step-up re-authentication
    "apps/web/src/routes/tree.tsx",  # wires the guards to every route; no session -> /login
    "apps/web/src/shell/bootstrap/bootstrap.ts",  # `/me` -> the session claims the guards read
)
MANIFESTS: tuple[str, ...] = ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", ".npmrc")
MANIFESTS += (".pnpmfile.cjs", "pyproject.toml", "uv.lock", "Cargo.toml", "Cargo.lock")
POSTINSTALL = "tools/ci/allowed-postinstall.json"
GATE = ("tools/ci/security_review_label.py", "scripts/tests/test_security_review_label.py")
WORDS = ("key", "secret", "token", "crypt")
API_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, http.client.HTTPException)


def _literal(path: str) -> str:
    """A path as ERE: a directory (`/` last) by prefix, a file exactly."""
    return path.replace(".", r"\.") + ("" if path.endswith("/") else "$")


def _any_case(word: str) -> str:
    return "".join(f"[{c.upper()}{c}]" for c in word)


RULES = (
    ("backend module", rf"^services/api/(candleviewer/)?({'|'.join(MODULES)})/"),
    ("infra", r"^infra/"),
    (
        "apps/web auth/session code",
        rf"^({'|'.join(map(_literal, WEB_AUTH_PATHS))}|apps/web/src/([^/]+/)*(auth|sessions?)/)",
    ),
    (
        "dependency manifest",
        rf"^(([^/]+/)*({'|'.join(map(_literal, MANIFESTS))}|requirements[^/]*\.txt$)|"
        rf"{_literal(POSTINSTALL)})",
    ),
    ("CI workflow file", rf"^(\.github/(workflows|actions)/|{'|'.join(map(_literal, GATE))})"),
    ("name glob", rf"^.*({'|'.join(map(_any_case, WORDS))})"),  # a directory's name counts too
)
_COMPILED = tuple((name, re.compile(pattern)) for name, pattern in RULES)
SECURITY_PATH_RE = re.compile("|".join(f"({pattern})" for _, pattern in RULES))


class GateError(Exception):
    pass


class Unsure(GateError):
    """The changed files could not all be read."""


class Api(Protocol):
    def get(self, path: str) -> Any: ...

    def post(self, path: str, body: dict[str, object]) -> Any: ...


class GitHubApi:
    """The REST API of one repository. The token goes only into the Authorization header."""

    def __init__(self, repo: str, token: str) -> None:
        self._repo = repo
        self._headers = {"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}
        self._headers["Accept"] = "application/vnd.github+json"

    def get(self, path: str) -> Any:
        return self._call("GET", path, None)

    def post(self, path: str, body: dict[str, object]) -> Any:
        return self._call("POST", path, json.dumps(body).encode())

    def _call(self, method: str, path: str, data: bytes | None) -> Any:
        url = f"https://api.github.com/repos/{self._repo}{path}"  # a fixed https host, nothing else
        with urllib.request.urlopen(
            urllib.request.Request(url, data, self._headers, method=method), timeout=30
        ) as resp:
            return json.load(resp)


def rule_for(path: str) -> str | None:
    """The first C-10.2 rule `path` matches, or None."""
    return next((name for name, regex in _COMPILED if regex.match(path)), None)


def changed_paths(api: Api, number: int, count: int) -> list[str]:
    """Every path the PR changes, a rename's old one too. Unsure if one may be missing."""
    if count > MAX_FILES:
        raise Unsure(f"the PR changes {count} files and the API lists at most {MAX_FILES}")
    files: list[Any] = []
    try:
        for page in range(1, MAX_FILES // PAGE + 1):
            batch = api.get(f"/pulls/{number}/files?per_page={PAGE}&page={page}")
            if not isinstance(batch, list):
                raise TypeError(f"page {page} is not a list")
            files += batch
            if len(batch) < PAGE:
                break
        paths = [str(p) for f in files for p in (f["filename"], f.get("previous_filename")) if p]
    except API_ERRORS as exc:
        raise Unsure(f"could not list the changed files ({exc})") from exc
    if len(files) != count:
        raise Unsure(f"the API listed {len(files)} of the PR's {count} changed files")
    return paths


def run(api: Api, number: int) -> int:
    pr = api.get(f"/pulls/{number}")
    labelled = LABEL in {label["name"] for label in pr["labels"]}
    try:
        paths = changed_paths(api, number, int(pr["changed_files"]))
    except Unsure as exc:
        if not labelled:
            raise
        print(f"::warning title=security-review-label::{exc}; `{LABEL}` is on the PR already")
        return 0
    hits = {path: rule for path in paths if (rule := rule_for(path)) is not None}
    if not hits:
        print("security-review-label: no C-10.2 security path is touched; nothing to do")
        return 0
    for path, rule in sorted(hits.items()):  # repr: a newline in a name cannot start a command
        print(f"C-10.2 security path ({rule}): {path!r}")
    if labelled:
        print(f"security-review-label: `{LABEL}` is on the PR already")
        return 0
    try:
        answer = api.post(f"/issues/{number}/labels", {"labels": [LABEL]})
        added = LABEL in {label["name"] for label in answer}
    except API_ERRORS as exc:
        raise GateError(f"could not add `{LABEL}` ({exc})") from exc
    if not added:
        raise GateError(f"the label API answered without `{LABEL}`")
    print(f"::notice title=security-review-label::added `{LABEL}` ({len(hits)} C-10.2 paths)")
    return 0


def main(argv: list[str] | None = None, api: Api | None = None) -> int:
    parser = argparse.ArgumentParser(description="Label a PR that touches a C-10.2 path (#2892).")
    parser.add_argument("--print-regex", action="store_true", help="print SECURITY_PATH_RE")
    if parser.parse_args(argv).print_regex:
        print(SECURITY_PATH_RE.pattern)
        return 0
    event, number = os.environ.get("EVENT_NAME", ""), os.environ.get("PR_NUMBER", "")
    if event == "merge_group":
        print("security-review-label: a merge group has no pull request to label")
        return 0
    try:
        if event != "pull_request" or not number.isdecimal():
            raise GateError(f"needs a pull_request event and its number, not {event!r} {number!r}")
        if api is None:
            repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN", "")
            if not (repo and token):
                raise GateError("GITHUB_REPOSITORY and GH_TOKEN are required")
            api = GitHubApi(repo, token)
        return run(api, int(number))
    except (GateError, *API_ERRORS) as exc:
        message = f"CI-GATE-004: {exc}; failing closed (docs/ci-runbook.md section 4)"
        print(f"::error title=security-review-label::{message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
