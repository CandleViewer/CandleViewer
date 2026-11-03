#!/usr/bin/env python3
"""Prepare, classify and verify a release candidate (#3099, docs/plan/07-release-and-prr.md §3, §4).

Releases are cut from `main` only and roll forward (07 §4): a reviewed release-prep PR
(`chore(infra-devops): prepare release X.Y.Z`, `CHANGELOG.md` + `version.txt` only) is the
candidate, and the release run tags it after verifying it. Three modes, one contract:

  prepare     `--rev REV [--date YYYY-MM-DD] [--allow-1-0-0] [--pr-labels-json PATH]`, run after
              `git fetch origin --tags`. Refuses a broken tag history; re-opens the topmost
              version section into Unreleased when no final tag carries it (a re-prep); syncs the
              commits since the nearest final tag reachable from REV; computes V, the C-15.5 next
              version of the line base, refusing a bump of none; finalises `## V — date` and
              writes `version.txt`. A pure function of (REV with its tags, date, flag, labels): it
              reads `CHANGELOG.md` from REV (never the working tree) and derives the version
              from the tags, so a re-run after every rebase is byte-identical. Prints the prep
              PR's title and its informational `type/release` label.
  --classify  `--rev AFTER [--before BEFORE]`: walks the first-parent commits in BEFORE..AFTER
              (AFTER alone without BEFORE) and prints `candidate=<sha>` for the one commit whose
              subject is the prep title (optionally ` (#N)`) or whose first-parent diff changes
              `version.txt`; `candidate=` when there is none. More than one candidate in one push
              is CI-REL-005 and names none: nothing is created.
  --verify    `--rev C [--allow-1-0-0] [--main-ref origin/main] [--section-out PATH]`, run after
              `git fetch origin --tags`: identity (version.txt = the top `## V` heading = the
              subject's version; Unreleased present and empty; the first-parent diff inside the
              prep allow-list), tag history (vV absent or at C; every other final tag reachable
              from C keeps its section; any other final tag is rogue unless it descends from C
              and is reachable from --main-ref, a later release on main), version (V = the C-15.5
              next version of the highest final tag in C's line, excluding vV, for the bump over
              (prevTag..C]; CI-REL-002 guard), completeness (every changelog-worthy commit in the
              range is referenced in the V section under the trailing-token rule; a sha7 shared
              by two commits reachable from C references nothing) and local provenance (C is an
              ancestor of --main-ref). The GitHub-verified check is the release run's, not this
              tool's.

Exit codes: 0 ok (or no candidate), 1 CI-REL-005 / CI-REL-002, a changelog format, labels or git
error. Stdlib only; no network (the caller fetches the tags).
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.ci.changelog_lib import (  # noqa: E402
    Bump,
    Category,
    ParsedCommit,
    build_changelog_update,
    pr_number,
)
from tools.ci.collect_commits import (  # noqa: E402
    CollectCommitsError,
    commits_since_last_tag,
    last_final_tag,
)
from tools.ci.finalize_changelog import finalize  # noqa: E402
from tools.ci.release_semver import Version, check_1_0_0_guard, compute_next_version  # noqa: E402
from tools.ci.update_changelog import (  # noqa: E402
    _CATEGORY_ORDER,
    ChangelogFormatError,
    PrLabelsError,
    _parse,
    _render_unreleased_section,
    _split_unreleased,
    load_pr_labels,
    merge_unreleased,
    referenced_tokens,
)

CHANGELOG = "CHANGELOG.md"
VERSION_FILE = "version.txt"
#: The prep allow-list (07 §4.1): extended only by the PR that adds a new release-prep artefact.
PREP_FILES = frozenset({CHANGELOG, VERSION_FILE})
PREP_LABEL = "type/release"
UNRELEASED_HEADING = "## Unreleased"
_VERSION = r"(?P<version>\d+\.\d+\.\d+)"
#: The prep PR title; the squash subject may add ` (#N)`.
PREP_TITLE_RE = re.compile(rf"^chore\(infra-devops\): prepare release {_VERSION}$")
PREP_SUBJECT_RE = re.compile(rf"^chore\(infra-devops\): prepare release {_VERSION}(?: \(#\d+\))?$")
_FINAL_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
_HEADING_RE = re.compile(rf"^## {_VERSION} — \d{{4}}-\d{{2}}-\d{{2}}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ZERO_SHA_RE = re.compile(r"^0+$")
REL_005 = "CI-REL-005"
REL_002 = "CI-REL-002"


class ReleaseError(Exception):
    """A refused prepare or a git failure; `code` is the CI error code it reports."""

    def __init__(self, message: str, code: str = REL_005) -> None:
        super().__init__(message)
        self.code = code


def _git(repo: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", repo, "-c", "log.showSignature=false", *args]
    done = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", check=False)
    if check and done.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done


def resolve(repo: str, rev: str) -> str:
    """The commit sha `rev` names; a ReleaseError when it names none."""
    if rev.startswith("-"):
        raise ReleaseError(f"unknown revision {rev!r}")
    done = _git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False)
    if done.returncode != 0:
        raise ReleaseError(f"unknown revision {rev!r}")
    return done.stdout.strip()


def show(repo: str, sha: str, path: str) -> str | None:
    """`path` at `sha`, or None when it does not exist there."""
    done = _git(repo, "show", f"{sha}:{path}", check=False)
    return done.stdout if done.returncode == 0 else None


def final_tags(repo: str) -> dict[str, str]:
    """Final `vX.Y.Z` tag name -> the commit it points at (annotated tags peeled)."""
    fmt = "%(refname:strip=2) %(objectname) %(*objectname)"
    out = _git(repo, "for-each-ref", f"--format={fmt}", "refs/tags/v*").stdout
    tags: dict[str, str] = {}
    for line in out.splitlines():
        name, obj, *peeled = line.split()
        if _FINAL_TAG_RE.match(name):
            tags[name] = peeled[0] if peeled else obj
    return tags


def is_ancestor(repo: str, ancestor: str, rev: str) -> bool:
    return _git(repo, "merge-base", "--is-ancestor", ancestor, rev, check=False).returncode == 0


def changed_files(repo: str, sha: str) -> set[str]:
    """Paths `sha` changes against its first parent (everything, for a root commit)."""
    parents = _git(repo, "rev-list", "--parents", "-n", "1", sha).stdout.split()[1:]
    if parents:
        out = _git(repo, "diff", "--no-renames", "--name-only", parents[0], sha).stdout
    else:
        out = _git(repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha).stdout
    return set(out.split())


def section_versions(text: str) -> list[str]:
    """The versions of the `## X.Y.Z — YYYY-MM-DD` headings, top first."""
    return [m["version"] for line in text.splitlines() if (m := _HEADING_RE.match(line.rstrip()))]


def _section_bounds(lines: list[str], version: str) -> tuple[int, int] | None:
    for start, line in enumerate(lines):
        found = _HEADING_RE.match(line.rstrip())
        if found and found["version"] == version:
            end = next(
                (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines)
            )
            return start, end
    return None


def version_section(text: str, version: str) -> list[str]:
    """The lines of the `## version — date` section, heading included; [] when absent."""
    lines = text.splitlines()
    bounds = _section_bounds(lines, version)
    return lines[bounds[0] : bounds[1]] if bounds else []


def tag_history_errors(
    repo: str, sha: str, text: str, exclude: str | None = None, main: str | None = None
) -> list[str]:
    """Every final tag reachable from `sha` (but `exclude`) keeps its section in `text`; every
    other final tag is rogue (roll-forward), except a later release on main: a tag whose target
    descends from `sha` and is reachable from `main`. Without `main` nothing is exempt."""
    versions = set(section_versions(text))
    errors = []
    for tag, target in sorted(final_tags(repo).items()):
        if tag == exclude:
            continue
        if is_ancestor(repo, target, sha):
            if tag[1:] not in versions:
                errors.append(f"tag {tag} is reachable but its section '## {tag[1:]}' is missing")
        elif not (
            main is not None and is_ancestor(repo, sha, target) and is_ancestor(repo, target, main)
        ):
            errors.append(
                f"tag {tag} is outside the line of {sha[:7]} (rogue: releases roll forward from "
                "main, 07 §4; removing it is a manual act)"
            )
    return errors


def line_base(repo: str, sha: str, exclude: str | None = None) -> Version:
    """The highest final tag reachable from `sha` (but `exclude`), or 0.0.0."""
    reachable = [
        Version.parse(tag)
        for tag, target in final_tags(repo).items()
        if tag != exclude and is_ancestor(repo, target, sha)
    ]
    return max(reachable, key=lambda v: (v.major, v.minor, v.patch), default=Version(0, 0, 0))


def range_commits(
    repo: str, sha: str, exclude: str | None = None, labels: dict[int, frozenset[str]] | None = None
) -> tuple[str | None, list[ParsedCommit]]:
    """(prevTag, the parsed commits in (prevTag..sha]), prevTag excluding `exclude`."""
    try:
        prev = last_final_tag(sha, repo, exclude)
        raw = commits_since_last_tag(sha, repo, exclude)
    except CollectCommitsError as exc:
        raise ReleaseError(str(exc)) from exc
    return prev, _parse(raw, labels or {})


def _worthy(commit: ParsedCommit) -> bool:
    """A commit the changelog lists (build_changelog_update's rule)."""
    if commit.is_merge or not commit.is_conventional:
        return False
    return commit.security_summary is not None or commit.category is not None


def missing_commits(
    commits: list[ParsedCommit], section: list[str], reachable: list[str]
) -> list[ParsedCommit]:
    """The changelog-worthy `commits` no entry line of `section` references by its trailing
    token; a sha7 that two `reachable` commits share references nothing."""
    entries = [line for line in section if line.strip().startswith("- ")]
    tokens = referenced_tokens(entries)
    shared = {short for short, n in Counter(s[:7] for s in reachable).items() if n > 1}
    missing = []
    for commit in filter(_worthy, commits):
        short = commit.sha[:7]
        number = pr_number(commit.subject_line)
        if (short in tokens and short not in shared) or (
            number is not None and f"#{number}" in tokens
        ):
            continue
        missing.append(commit)
    return missing


def classify(repo: str, after: str, before: str | None = None) -> list[tuple[str, str | None]]:
    """[(sha, subject version or None)] for each candidate among the pushed first-parent commits."""
    head = resolve(repo, after)
    if before is None or _ZERO_SHA_RE.match(before):
        shas = [head]
    else:
        base = resolve(repo, before)
        shas = _git(repo, "rev-list", "--first-parent", f"{base}..{head}").stdout.split()
    found = []
    for sha in shas:
        subject = _git(repo, "log", "-1", "--format=%s", sha).stdout.strip()
        match = PREP_SUBJECT_RE.match(subject)
        if match or VERSION_FILE in changed_files(repo, sha):
            found.append((sha, match["version"] if match else None))
    return found


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


def verify(
    repo: str, rev: str, *, allow_1_0_0: bool = False, main_ref: str = "origin/main"
) -> tuple[str | None, list[Finding]]:
    """(V, findings) for candidate `rev`; no findings means every check of the module holds."""
    sha = resolve(repo, rev)
    text = show(repo, sha, CHANGELOG)
    raw_version = show(repo, sha, VERSION_FILE)
    if text is None or raw_version is None:
        return None, [Finding(REL_005, f"{sha[:7]} has no {CHANGELOG} or no {VERSION_FILE}")]
    try:
        version = Version.parse(raw_version)
    except ValueError:
        return None, [Finding(REL_005, f"{VERSION_FILE} at {sha[:7]} is not X.Y.Z")]
    v = str(version)
    vtag = f"v{v}"
    out: list[Finding] = []

    def fail(message: str, code: str = REL_005) -> None:
        out.append(Finding(code, message))

    # identity
    headings = section_versions(text)
    if not headings or headings[0] != v:
        fail(f"top version heading {headings[0] if headings else 'none'} != {VERSION_FILE} {v}")
    subject = _git(repo, "log", "-1", "--format=%s", sha).stdout.strip()
    titled = PREP_SUBJECT_RE.match(subject)
    if titled and titled["version"] != v:
        fail(f"subject version {titled['version']} != {VERSION_FILE} {v}")
    try:
        unreleased = sum(len(lines) for lines in _split_unreleased(text)[2].values())
    except ChangelogFormatError as exc:
        fail(f"{CHANGELOG}: {exc}")
    else:
        if UNRELEASED_HEADING not in {line.strip() for line in text.splitlines()}:
            fail(f"{CHANGELOG} has no '{UNRELEASED_HEADING}' heading: a candidate keeps it, empty")
        elif unreleased:
            fail(f"Unreleased is not empty ({unreleased} entries): a candidate finalises it all")
    outside = sorted(changed_files(repo, sha) - PREP_FILES)
    if outside:
        fail(f"{sha[:7]} changes files outside the prep allow-list: {', '.join(outside[:5])}")
    try:
        main: str | None = resolve(repo, main_ref)
    except ReleaseError:
        main = None
    # tag history (a later release is exempt only on main; unresolved main exempts nothing)
    tags = final_tags(repo)
    if vtag in tags and tags[vtag] != sha:
        fail(f"tag {vtag} exists elsewhere ({tags[vtag][:7]}); a tag is never moved")
    for message in tag_history_errors(repo, sha, text, exclude=vtag, main=main):
        fail(message)
    # version
    base = line_base(repo, sha, exclude=vtag)
    prev, commits = range_commits(repo, sha, exclude=vtag)
    span = f"{prev or 'the root'}..{sha[:7]}"
    guard = check_1_0_0_guard(base, version, allow_1_0_0=allow_1_0_0)
    bump = build_changelog_update(commits).bump
    if not guard.ok:
        fail(f"{guard.reason} (line base {base}, {VERSION_FILE} {v})", REL_002)
    elif bump is Bump.NONE:
        fail(f"no changelog-worthy commit in {span}: a bump of none is no release")
    else:
        expected = compute_next_version(base, bump, allow_1_0_0=allow_1_0_0).next_version
        if expected != version:
            fail(f"version {v} != expected {expected} ({bump.value} bump over {span})")
    # completeness
    reachable = _git(repo, "rev-list", sha).stdout.split()
    for commit in missing_commits(commits, version_section(text, v), reachable):
        fail(
            f"commit {commit.sha[:7]} {commit.subject_line!r} is not referenced in the {v} section"
        )
    # provenance (local half; the release run adds the GitHub-verified check)
    if main is None:
        fail(f"cannot resolve {main_ref}: fetch it first (git fetch origin --tags)")
    elif not is_ancestor(repo, sha, main):
        fail(f"{sha[:7]} is not reachable from {main_ref}: releases are cut from main only")
    return v, out


def reopen(text: str, version: str) -> str:
    """Move the `## version` section's entries back into Unreleased, verbatim and first."""
    lines = text.splitlines()
    bounds = _section_bounds(lines, version)
    if bounds is None:
        return text
    start, end = bounds
    reopened: dict[Category, list[str]] = {}
    current: Category | None = None
    for number, line in enumerate(lines[start + 1 : end], start=start + 2):
        stripped = line.strip()
        heading = next((c for c in _CATEGORY_ORDER if stripped == f"### {c.value}"), None)
        if heading is not None:
            current = heading
        elif current is not None and stripped.startswith("- "):
            reopened.setdefault(current, []).append(line)
        elif stripped:
            raise ChangelogFormatError(
                f"line {number}: unexpected content in the untagged '## {version}' section, "
                f"which a re-prep re-opens: {line!r}"
            )
    remaining = "\n".join(lines[:start] + lines[end:]) + "\n"
    before, after, entries, _ = _split_unreleased(remaining)
    for cat, kept in entries.items():
        seen = {line.rstrip() for line in reopened.get(cat, [])}
        reopened.setdefault(cat, []).extend(x for x in kept if x.rstrip() not in seen)
    return before + "\n".join(_render_unreleased_section(reopened)) + "\n" + after


@dataclass(frozen=True)
class Prepared:
    version: str
    changelog: str
    version_text: str
    pending: int

    @property
    def title(self) -> str:
        return f"chore(infra-devops): prepare release {self.version}"


def prepare(
    repo: str,
    rev: str,
    date: str,
    *,
    allow_1_0_0: bool = False,
    labels: dict[int, frozenset[str]] | None = None,
) -> Prepared:
    """The release-prep content for base tip `rev` (module docstring, prepare)."""
    sha = resolve(repo, rev)
    text = show(repo, sha, CHANGELOG)
    if text is None:
        raise ReleaseError(f"{sha[:7]} has no {CHANGELOG}")
    # no exemption: a tag descending from the base tip is off main by definition (07 §4)
    broken = tag_history_errors(repo, sha, text)
    if broken:
        raise ReleaseError("tag history is broken: " + "; ".join(broken))
    tags = final_tags(repo)
    headings = section_versions(text)
    if headings and f"v{headings[0]}" not in tags:
        text = reopen(text, headings[0])
    prev, commits = range_commits(repo, sha, labels=labels)
    merged = merge_unreleased(text, commits)
    if merged.security_violations or merged.refused_footers:
        raise ReleaseError(
            "Security changelog wording check failed (07 §3): "
            f"{len(merged.security_violations)} line(s), refused footers "
            f"{', '.join(merged.refused_footers) or 'none'}"
        )
    bump = build_changelog_update(commits).bump
    if bump is Bump.NONE:
        raise ReleaseError(
            f"no changelog-worthy commit since {prev or 'the root'}: nothing to release"
        )
    base = line_base(repo, sha)
    version = compute_next_version(base, bump, allow_1_0_0=allow_1_0_0).next_version
    if version is None:  # unreachable: a real bump always yields a version
        raise ReleaseError(f"no next version for {base} and a {bump.value} bump")
    if f"v{version}" in tags:
        raise ReleaseError(f"tag v{version} already exists elsewhere; a tag is never moved")
    finalised, _ = finalize(merged.text, str(version), date)
    return Prepared(str(version), finalised, f"{version}\n", merged.pending)


def _is_calendar_date(text: str) -> bool:
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _error(code: str, message: str) -> None:
    text = f"{code}: {message}".replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error::{text}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--classify", action="store_true", help="find the candidate in a push")
    mode.add_argument("--verify", action="store_true", help="verify candidate --rev")
    parser.add_argument("--rev", required=True, help="prepare: base tip; else the candidate/push")
    parser.add_argument("--before", default=None, help="--classify: the push's previous tip")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--date", default=None, help="prepare: YYYY-MM-DD (today, UTC)")
    parser.add_argument("--allow-1-0-0", action="store_true", help="the 1.0.0 declaration")
    parser.add_argument("--main-ref", default="origin/main", help="--verify: provenance ref")
    parser.add_argument("--section-out", type=Path, default=None, help="--verify: V section")
    parser.add_argument("--pr-labels-json", type=Path, default=None, help="prepare: PR labels")
    args = parser.parse_args(argv)
    repo = args.repo
    try:
        if args.classify:
            found = classify(repo, args.rev, args.before)
            if len(found) > 1:
                listed = ", ".join(sha[:7] for sha, _ in found)
                _error(
                    REL_005,
                    f"{len(found)} release candidates in one push ({listed}); none "
                    "is released: re-prep and merge the prep PR alone (07 §4)",
                )
                return 1
            print(f"candidate={found[0][0] if found else ''}")
            return 0
        if args.verify:
            version, findings = verify(
                repo, args.rev, allow_1_0_0=args.allow_1_0_0, main_ref=args.main_ref
            )
            for finding in findings:
                _error(finding.code, finding.message)
            if findings or version is None:
                return 1
            if args.section_out is not None:
                text = show(repo, resolve(repo, args.rev), CHANGELOG) or ""
                body = "\n".join(version_section(text, version)).rstrip("\n") + "\n"
                args.section_out.write_text(body, encoding="utf-8", newline="\n")
            print(f"version={version}")
            print(f"verified: {resolve(repo, args.rev)}")
            return 0
        date = args.date or dt.datetime.now(dt.UTC).date().isoformat()
        if not _DATE_RE.match(date) or not _is_calendar_date(date):
            parser.error("--date must be a real YYYY-MM-DD date")
        labels = load_pr_labels(args.pr_labels_json)
        prepared = prepare(repo, args.rev, date, allow_1_0_0=args.allow_1_0_0, labels=labels)
    except ReleaseError as exc:
        _error(exc.code, str(exc))
        return 1
    except (ChangelogFormatError, PrLabelsError) as exc:
        _error(REL_005, str(exc))
        return 1
    root = Path(repo)
    (root / CHANGELOG).write_text(prepared.changelog, encoding="utf-8", newline="\n")
    (root / VERSION_FILE).write_text(prepared.version_text, encoding="utf-8", newline="\n")
    print(f"version={prepared.version}")
    print(f"title={prepared.title}")
    print(f"label={PREP_LABEL} (informational; pr-metadata judges the shape, 07 §3)")
    print(f"pending synced: {prepared.pending}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
