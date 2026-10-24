#!/usr/bin/env python3
"""E03-T11: conventional-commit parsing, changelog grouping and semver bump.

`docs/plan/07-release-and-prr.md` §2 (semver rules) and §3 (changelog
automation); ADR-0013 pipeline shape ("release tag -> changelog -> Electron
installers (signed) -> release checklist + PRR gate").

This module is the shared, unit-testable core used by both
`.github/workflows/changelog.yml` (read-only preview of `Unreleased`; the
sync lands via reviewed PRs) and `.github/workflows/release.yml` (compute the semver bump and
finalise the `Unreleased` section at a release-train cut). It has no GitHub
API calls and no I/O beyond what its callers pass in, so it is exercised
entirely by fixture-driven unit tests (stdlib only, no network).

Error codes referenced by callers (ticket "Technical notes"):
  CI-REL-001 unparseable changelog fragment
  CI-REL-002 1.0.0 guard
  CI-REL-003 unsigned release tag
  CI-REL-004 release checklist incomplete
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# Conventional-commit header: `type(scope)!: subject` — scope optional, `!`
# optional (breaking-change shorthand per docs/plan/01-sdlc-and-branching.md §6).
_HEADER_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<subject>.+)$"
)
_BREAKING_FOOTER_RE = re.compile(r"^BREAKING[ -]CHANGE:\s*(.+)$", re.MULTILINE)
# `[ \t]*`, never `\s*`: an empty footer line must not take the next line as its summary.
_CHANGELOG_FOOTER_RE = re.compile(r"^Changelog:[ \t]*(\S.*)$", re.MULTILINE)
# #4435 (07 §3): a security fix's impact-only summary; the sync renders it under Security.
_SECURITY_FOOTER_RE = re.compile(r"^Changelog-Security:[ \t]*(.*)$", re.MULTILINE)
_PR_NUMBER_RE = re.compile(r"\(#(\d+)\)")
_MERGE_COMMIT_RE = re.compile(r"^Merge (pull request|branch|remote-tracking branch)\b")

# Exempt PR-title prefixes (ticket: "except for chore:/ci:/docs:-only PRs").
EXEMPT_TYPES = frozenset({"chore", "ci", "docs"})

# Security wording guard (ticket "Scope / Deliverables" — Security-fix
# wording guard): reject exploit/PoC detail in a Security changelog line.
_EXPLOIT_MARKERS = (
    "exploit",
    "payload",
    "poc",
    "proof of concept",
    "proof-of-concept",
    "cve-",
)


class Category(str, Enum):
    """The five changelog groups (ticket "Scope / Deliverables")."""

    FEATURES = "Features"
    FIXES = "Fixes"
    PERFORMANCE = "Performance"
    SECURITY = "Security"
    BREAKING = "Breaking Changes"


class Bump(str, Enum):
    NONE = "none"
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


_BUMP_ORDER = {Bump.NONE: 0, Bump.PATCH: 1, Bump.MINOR: 2, Bump.MAJOR: 3}

# Which conventional-commit type maps to which changelog category and bump.
_TYPE_TO_CATEGORY = {
    "feat": Category.FEATURES,
    "fix": Category.FIXES,
    "perf": Category.PERFORMANCE,
}
_TYPE_TO_BUMP = {
    "feat": Bump.MINOR,
    "fix": Bump.PATCH,
    "perf": Bump.PATCH,
}


@dataclass(frozen=True)
class ParsedCommit:
    """A single parsed conventional-commit (or a rejected non-conventional one)."""

    sha: str
    subject_line: str
    is_conventional: bool
    is_merge: bool = False
    type: str | None = None
    scope: str | None = None
    subject: str | None = None
    breaking: bool = False
    breaking_detail: str | None = None
    category: Category | None = None
    bump: Bump = Bump.NONE
    security_summary: str | None = None
    security_rejected: str | None = None  # a footer dropped (empty or failed the wording check)

    def security_line(self) -> str:
        """The `Changelog-Security:` summary as a bullet ending with the PR's `(#N)` (or sha7)."""
        summary = (self.security_summary or "").strip()
        prs = _PR_NUMBER_RE.findall(self.subject_line)
        token = f"(#{prs[-1]})" if prs else f"({self.sha[:7]})"
        return f"- {summary}" if summary.endswith(token) else f"- {summary} {token}"

    def changelog_line(self) -> str:
        scope_part = f"**{self.scope}**: " if self.scope else ""
        short_sha = self.sha[:7] if self.sha else ""
        suffix = f" ({short_sha})" if short_sha else ""
        return f"- {scope_part}{self.subject}{suffix}"


def _visible(text: str) -> str:
    """`text` without what GitHub does not render: HTML comments and fenced or indented code.
    Mirrors the first three steps of `tools/ci/check_pr_metadata.py` `strip_markup` (not imported:
    that script is the gate's own, and its inline-span step would alter a summary's backticks)."""
    text = re.sub(r"<!--.*?(?:-->|\Z)", "", text, flags=re.S)
    text = re.sub(r"(```|~~~).*?(?:\1|\Z)", "", text, flags=re.S)
    return re.sub(r"^(?: {4}|\t).*$", "", text, flags=re.M)


def security_footer(text: str) -> tuple[str | None, str | None]:
    """(kept, rejected) for the visible `Changelog-Security:` footer in `text`. A summary that is
    empty or fails `check_security_wording` is rejected, so it never reaches CHANGELOG.md."""
    found = _SECURITY_FOOTER_RE.search(_visible(text or ""))
    if found is None:
        return None, None
    summary = found.group(1).strip()
    if summary and check_security_wording([summary]).ok:
        return summary, None
    return None, summary


def parse_commit(sha: str, message: str) -> ParsedCommit:
    """Parse a single commit message into a `ParsedCommit`.

    Merge commits are recognised and excluded from changelog generation
    (ticket test-plan fixture corpus: "merge commits").
    """
    lines = message.splitlines()
    header = lines[0] if lines else ""
    body = "\n".join(lines[1:])

    if _MERGE_COMMIT_RE.match(header):
        return ParsedCommit(sha=sha, subject_line=header, is_conventional=False, is_merge=True)

    m = _HEADER_RE.match(header.strip())
    if not m:
        return ParsedCommit(sha=sha, subject_line=header, is_conventional=False)

    commit_type = m.group("type")
    scope = m.group("scope")
    bang = bool(m.group("bang"))
    subject = m.group("subject").strip()

    footer_match = _BREAKING_FOOTER_RE.search(body)
    breaking = bang or footer_match is not None
    breaking_detail = footer_match.group(1).strip() if footer_match else None

    if breaking:
        bump = Bump.MAJOR
        category: Category | None = Category.BREAKING
    else:
        bump = _TYPE_TO_BUMP.get(commit_type, Bump.NONE)
        category = _TYPE_TO_CATEGORY.get(commit_type)

    # `revert` commits: treated as conventional (so they don't trip the
    # fragment check) but contribute no changelog entry / no bump, unless
    # they themselves carry a BREAKING CHANGE footer.
    if commit_type == "revert" and not breaking:
        bump = Bump.NONE
        category = None

    kept, rejected = security_footer(body)
    return ParsedCommit(
        sha=sha,
        subject_line=header,
        security_summary=kept,
        security_rejected=rejected,
        is_conventional=True,
        type=commit_type,
        scope=scope,
        subject=subject,
        breaking=breaking,
        breaking_detail=breaking_detail,
        category=category,
        bump=bump,
    )


@dataclass
class ChangelogUpdate:
    """Grouped changelog entries plus the aggregate semver bump."""

    entries: dict[Category, list[str]] = field(default_factory=dict)
    bump: Bump = Bump.NONE
    triggering_breaking_commits: list[str] = field(default_factory=list)

    def has_entries(self) -> bool:
        return any(self.entries.values())


def build_changelog_update(commits: list[ParsedCommit]) -> ChangelogUpdate:
    """Group parsed commits by category and compute the aggregate bump.

    Highest-wins bump semantics: any BREAKING CHANGE / `!` commit forces
    MAJOR regardless of how many `fix:`/`feat:` commits also landed
    (acceptance scenario "A breaking change forces a MAJOR bump proposal").
    """
    update = ChangelogUpdate()
    for commit in commits:
        if commit.is_merge or not commit.is_conventional:
            continue
        if _BUMP_ORDER[commit.bump] > _BUMP_ORDER[update.bump]:
            update.bump = commit.bump
        if commit.breaking:
            update.triggering_breaking_commits.append(commit.sha or commit.subject_line)
        if commit.security_summary is not None:
            # A security fix is called out by its impact-only line alone: the type bullet
            # would list the same commit twice. A breaking change keeps its own bullet.
            update.entries.setdefault(Category.SECURITY, []).append(commit.security_line())
            if commit.breaking:
                update.entries.setdefault(Category.BREAKING, []).append(commit.changelog_line())
        elif commit.category is not None:
            update.entries.setdefault(commit.category, []).append(commit.changelog_line())
    return update


def is_pr_exempt(title: str) -> bool:
    """`chore:`/`ci:`/`docs:`-only PRs are exempt from the fragment check."""
    m = _HEADER_RE.match(title.strip())
    if not m:
        return False
    return m.group("type") in EXEMPT_TYPES


@dataclass(frozen=True)
class FragmentCheckResult:
    ok: bool
    reason: str | None = None
    error_code: str | None = None


def check_changelog_fragment(title: str, body: str) -> FragmentCheckResult:
    """CI-REL-001: a PR needs a conventional title or a `Changelog:` footer.

    Acceptance scenario "A PR without a usable changelog line is blocked".
    """
    body = _visible(body or "")
    kept, rejected = security_footer(body)
    if rejected is not None:
        return FragmentCheckResult(
            ok=False,
            reason=(
                "The 'Changelog-Security:' footer is empty or fails the Security wording check. "
                "Keep it to the impact (docs/plan/07-release-and-prr.md §3); the detail stays in "
                "the internal finding tracker."
            ),
            error_code="CI-REL-001",
        )

    if is_pr_exempt(title):
        return FragmentCheckResult(ok=True)

    if _HEADER_RE.match(title.strip()):
        return FragmentCheckResult(ok=True)

    if _CHANGELOG_FOOTER_RE.search(body) or kept is not None:
        return FragmentCheckResult(ok=True)

    return FragmentCheckResult(
        ok=False,
        reason=(
            "PR title is not a conventional-commit header and no 'Changelog: <summary>' "
            "footer was found in the PR body. Add one or the other (docs/plan/"
            "07-release-and-prr.md §3)."
        ),
        error_code="CI-REL-001",
    )


@dataclass(frozen=True)
class SecurityWordingResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


def check_security_wording(security_lines: list[str]) -> SecurityWordingResult:
    """Warn on exploit/PoC detail in `Security` changelog entries.

    Ticket: "entries under Security must not include exploit detail; a lint
    warns on lines containing CVE proof-of-concept markers or the words
    'exploit'/'payload', pointing the author to the internal finding tracker."
    """
    violations = []
    for line in security_lines:
        lowered = line.lower()
        if any(marker in lowered for marker in _EXPLOIT_MARKERS):
            violations.append(line)
    return SecurityWordingResult(ok=not violations, violations=violations)
