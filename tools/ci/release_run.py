#!/usr/bin/env python3
"""The release run's GitHub steps (#3099, `.github/workflows/release.yml`, 07 §4).

`prepare_release.py --verify` decides on git facts; this tool does what needs the GitHub API, each
step idempotent, so a re-run on the same candidate creates no second tag, issue, release or comment:

  verified      `--candidate C`: C's commit is GitHub-verified (04 §12.3), else CI-REL-005.
  tag           `--candidate C --version V`: the annotated tag vV at C, made through the REST git
                database (no git push, no persisted credential). A no-op when vV already points at
                C; CI-REL-005 when it points elsewhere: a tag is never moved or deleted.
  checklist     `--version V`: finds or creates the `[Release]: vV checklist` issue; prints issue=N.
                Only an issue the release automation opened counts: anyone may open an issue from
                the template, and the PRR gate (CI-REL-004) is ticked on this one.
  draft         `--candidate C --version V --notes-file F`: finds or creates the draft release vV
                (target C, body F, the V section). A draft keeps body F on a re-run. A published
                release is CI-REL-005: its body and assets are immutable (C-15.7, built once and
                promoted), so a re-run never rebuilds or replaces what shipped. A body past the API
                limit is cut, pointing at CHANGELOG.md.
  comment       `--issue N --version V --body-file F`: one SBOM-diff comment per version on the
                checklist issue, the automation's own, edited in place on a re-run; a long body is
                cut, pointing at the attached `sbom-diff.md`.
  previous-tag  `--rev C [--exclude vV]`: the nearest final tag reachable from C but vV; prints
                previous=<tag or empty>. No network.
  untagged      `[--repo DIR] [--changelog PATH] [--summary PATH]`: the topmost version section no
                final tag carries (an untagged candidate), for the changelog preview. No network.

The API calls run `gh api` with the job's token (GH_TOKEN) on GITHUB_REPOSITORY. Values arrive as
arguments from env-only workflow values. Results print as `key=value` lines, which the workflow
greps (never the whole stdout); a refusal prints `::error::CI-REL-005: …` and exits 1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.ci.collect_commits import CollectCommitsError, last_final_tag  # noqa: E402
from tools.ci.prepare_release import (  # noqa: E402
    ReleaseError,
    final_tags,
    section_versions,
)

#: (method, path, JSON payload or None) -> the parsed JSON response.
Api = Callable[[str, str, dict[str, Any] | None], Any]

REL_005 = "CI-REL-005"
BOT = "github-actions[bot]"
CHECKLIST_LABELS = ["type/release", "priority/p1-high"]  # the release-checklist form's labels
PER_PAGE = 100
MAX_PAGES = 50
#: GitHub's limits are 125,000 characters for a release body and 65,536 for a comment.
MAX_RELEASE_BODY = 120_000
MAX_COMMENT = 60_000
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class RunError(Exception):
    """A refused step; the release run creates nothing further."""


def gh_api(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    """`gh api` with the job's token; the payload goes in on stdin, never on the command line."""
    cmd = ["gh", "api", "-X", method, "-H", "Accept: application/vnd.github+json", path]
    if payload is not None:
        cmd += ["--input", "-"]
    done = subprocess.run(
        cmd,
        input=None if payload is None else json.dumps(payload),
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if done.returncode != 0:
        raise RunError(f"gh api {method} {path} failed: {done.stderr.strip()[:500]}")
    return json.loads(done.stdout) if done.stdout.strip() else None


def _pages(api: Api, path: str) -> Iterator[dict[str, Any]]:
    sep = "&" if "?" in path else "?"
    for page in range(1, MAX_PAGES + 1):
        items = api("GET", f"{path}{sep}per_page={PER_PAGE}&page={page}", None)
        if not isinstance(items, list):
            raise RunError(f"GET {path}: expected a list")
        yield from items
        if len(items) < PER_PAGE:
            return
    raise RunError(f"GET {path}: more than {MAX_PAGES} pages")


def _by_bot(item: dict[str, Any]) -> bool:
    user = item.get("user")
    return isinstance(user, dict) and user.get("login") == BOT


def _cut(text: str, limit: int, pointer: str) -> str:
    """`text`, or its first whole lines under `limit` followed by `pointer`."""
    if len(text) <= limit:
        return text
    head = text[: limit - len(pointer) - 2]
    return head[: head.rfind("\n") + 1] + "\n" + pointer + "\n"


def is_verified(api: Api, repo: str, sha: str) -> bool:
    data = api("GET", f"repos/{repo}/commits/{sha}", None)
    commit = data.get("commit") if isinstance(data, dict) else None
    verification = commit.get("verification") if isinstance(commit, dict) else None
    return isinstance(verification, dict) and verification.get("verified") is True


def tag_target(api: Api, repo: str, tag: str) -> str | None:
    """The commit `refs/tags/<tag>` names (annotated tags peeled), or None when it is absent."""
    for ref in api("GET", f"repos/{repo}/git/matching-refs/tags/{tag}", None) or []:
        if ref.get("ref") != f"refs/tags/{tag}":
            continue  # matching-refs is a prefix match: v0.1.1 also lists v0.1.10
        obj = ref["object"]
        for _ in range(5):
            if obj["type"] == "commit":
                return str(obj["sha"])
            if obj["type"] != "tag":
                raise RunError(f"{tag} points at a {obj['type']}, not a commit")
            obj = api("GET", f"repos/{repo}/git/tags/{obj['sha']}", None)["object"]
        raise RunError(f"{tag}: tag chain deeper than 5")
    return None


def ensure_tag(api: Api, repo: str, version: str, sha: str) -> bool:
    """Create the annotated tag v<version> at `sha`; False when it is already there."""
    tag = f"v{version}"
    found = tag_target(api, repo, tag)
    if found == sha:
        return False
    if found is not None:
        raise RunError(
            f"tag {tag} points at {found[:7]}, not the candidate {sha[:7]}; a tag is never moved "
            "(docs/ci-runbook.md CI-REL-005: rogue tags are the owner's to remove)"
        )
    payload = {"tag": tag, "message": f"CandleViewer {tag}", "object": sha, "type": "commit"}
    obj = api("POST", f"repos/{repo}/git/tags", payload)
    try:
        api("POST", f"repos/{repo}/git/refs", {"ref": f"refs/tags/{tag}", "sha": obj["sha"]})
    except RunError:
        if tag_target(api, repo, tag) == sha:  # a concurrent run of the same candidate won
            return False
        raise
    return True


def checklist_title(version: str) -> str:
    return f"[Release]: v{version} checklist"


def ensure_checklist(api: Api, repo: str, version: str, run_url: str = "") -> tuple[int, bool]:
    """The automation's `[Release]: vV checklist` issue (number, created)."""
    title = checklist_title(version)
    for issue in _pages(api, f"repos/{repo}/issues?state=all&labels=type%2Frelease"):
        if "pull_request" not in issue and issue.get("title") == title and _by_bot(issue):
            return int(issue["number"]), False
    body = (
        f"Release checklist for `v{version}` (docs/plan/07-release-and-prr.md §4; the items are in "
        ".github/ISSUE_TEMPLATE/release-checklist.yml). The release run tagged the verified "
        "candidate and drafted the release; it stays a draft until the PRR gate item here is "
        "checked (CI-REL-004)."
    )
    if run_url:
        body += f"\n\nRelease run: {run_url}"
    issue = api(
        "POST", f"repos/{repo}/issues", {"title": title, "labels": CHECKLIST_LABELS, "body": body}
    )
    return int(issue["number"]), True


def release_body(version: str, notes: str) -> str:
    pointer = f"_Cut at GitHub's size limit: the full section is in CHANGELOG.md at `v{version}`._"
    return _cut(notes, MAX_RELEASE_BODY, pointer)


def _published_error(tag: str) -> RunError:
    return RunError(
        f"release {tag} is published; its body and assets are immutable (C-15.7): nothing is "
        "rebuilt or replaced. A fix ships as a new release (docs/ci-runbook.md CI-REL-005)"
    )


def ensure_draft(api: Api, repo: str, version: str, sha: str, notes: str) -> tuple[int, str]:
    """The draft release v<version> with body `notes` (id, what happened); published refuses."""
    tag = f"v{version}"
    body = release_body(version, notes)
    for rel in _pages(api, f"repos/{repo}/releases"):
        if rel.get("tag_name") != tag:
            continue
        if rel.get("draft") is not True:
            raise _published_error(tag)
        if rel.get("body") == body and rel.get("name") == tag:
            return int(rel["id"]), "kept"
        api("PATCH", f"repos/{repo}/releases/{rel['id']}", {"name": tag, "body": body})
        return int(rel["id"]), "updated"
    payload = {"tag_name": tag, "target_commitish": sha, "name": tag, "body": body, "draft": True}
    rel = api("POST", f"repos/{repo}/releases", payload)
    return int(rel["id"]), "created"


def comment_marker(version: str) -> str:
    return f"<!-- cv-release-sbom-diff v{version} -->"


def upsert_comment(api: Api, repo: str, issue: int, version: str, text: str) -> str:
    """One SBOM-diff comment per version, the automation's own; what happened."""
    marker = comment_marker(version)
    pointer = "_Cut at GitHub's size limit: the full diff is the release asset `sbom-diff.md`._"
    body = f"{marker}\n{_cut(text, MAX_COMMENT, pointer)}"
    for comment in _pages(api, f"repos/{repo}/issues/{issue}/comments"):
        if _by_bot(comment) and str(comment.get("body", "")).startswith(marker):
            if comment.get("body") == body:
                return "kept"
            api("PATCH", f"repos/{repo}/issues/comments/{comment['id']}", {"body": body})
            return "updated"
    api("POST", f"repos/{repo}/issues/{issue}/comments", {"body": body})
    return "created"


def untagged_version(repo: str, changelog_text: str) -> str | None:
    """The topmost version section's version when no final tag carries it."""
    versions = section_versions(changelog_text)
    if not versions or f"v{versions[0]}" in final_tags(repo):
        return None
    return versions[0]


def _error(message: str) -> None:
    text = f"{REL_005}: {message}".replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error::{text}")


def _sha(value: str) -> str:
    if not _SHA_RE.match(value):
        raise argparse.ArgumentTypeError("expected 40 lowercase hex")
    return value


def _version(value: str) -> str:
    if not _VERSION_RE.match(value):
        raise argparse.ArgumentTypeError("expected X.Y.Z")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="step", required=True)
    sub.add_parser("verified").add_argument("--candidate", type=_sha, required=True)
    tag = sub.add_parser("tag")
    tag.add_argument("--candidate", type=_sha, required=True)
    tag.add_argument("--version", type=_version, required=True)
    sub.add_parser("checklist").add_argument("--version", type=_version, required=True)
    draft = sub.add_parser("draft")
    draft.add_argument("--candidate", type=_sha, required=True)
    draft.add_argument("--version", type=_version, required=True)
    draft.add_argument("--notes-file", type=Path, required=True)
    comment = sub.add_parser("comment")
    comment.add_argument("--issue", type=int, required=True)
    comment.add_argument("--version", type=_version, required=True)
    comment.add_argument("--body-file", type=Path, required=True)
    prev = sub.add_parser("previous-tag")
    prev.add_argument("--rev", required=True)
    prev.add_argument("--exclude", default=None)
    prev.add_argument("--repo", default=".")
    untagged = sub.add_parser("untagged")
    untagged.add_argument("--repo", default=".")
    untagged.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    untagged.add_argument("--summary", type=Path, default=None)
    return parser


def _local(args: argparse.Namespace) -> int:
    if args.step == "previous-tag":
        print(f"previous={last_final_tag(args.rev, args.repo, args.exclude) or ''}")
        return 0
    found = untagged_version(args.repo, args.changelog.read_text(encoding="utf-8"))
    print(f"untagged={found or ''}")
    if found and args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(
                f"\n**Untagged candidate:** `## {found}` has no tag `v{found}`. The release run "
                "tags it after verify and the e2e gate, or refused it (CI-REL-005, "
                "`docs/ci-runbook.md`).\n"
            )
    return 0


def main(argv: list[str] | None = None, api: Api = gh_api) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.step in ("previous-tag", "untagged"):
            return _local(args)
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if not _SLUG_RE.match(repo):
            raise RunError("GITHUB_REPOSITORY is not owner/name")
        if args.step == "verified":
            if not is_verified(api, repo, args.candidate):
                raise RunError(
                    f"{args.candidate[:7]} is not GitHub-verified (04 §12.3); nothing is created"
                )
            print("verified=true")
        elif args.step == "tag":
            created = ensure_tag(api, repo, args.version, args.candidate)
            print(f"tag=v{args.version} ({'created' if created else 'already at the candidate'})")
        elif args.step == "checklist":
            server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
            run_id = os.environ.get("GITHUB_RUN_ID", "")
            run_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id.isdigit() else ""
            number, _ = ensure_checklist(api, repo, args.version, run_url)
            print(f"issue={number}")
        elif args.step == "draft":
            notes = args.notes_file.read_text(encoding="utf-8")
            if not notes.strip():
                raise RunError(f"the release notes for v{args.version} are empty")
            rel_id, what = ensure_draft(api, repo, args.version, args.candidate, notes)
            print(f"release={rel_id} ({what})")
        else:
            text = args.body_file.read_text(encoding="utf-8")
            print(f"comment={upsert_comment(api, repo, args.issue, args.version, text)}")
    except (RunError, ReleaseError, CollectCommitsError, OSError) as exc:
        _error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
