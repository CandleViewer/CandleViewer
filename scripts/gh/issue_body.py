"""Shared rendered-body parsing module for GitHub issue-forms bodies (E01-T07).

Implements the rendered-body contract established by E01-T05's issue forms and
locked down by ``scripts/tests/test_issue_form_contract.py``:

- Each answerable field renders as a ``### <Label>`` heading followed by its
  answer (or the literal ``_No response_`` placeholder when an optional field
  was left blank).
- A heading that is entirely absent from the body (not rendered at all, e.g. an
  older issue predating a form change) is distinguishable from a heading that is
  present but empty.
- The ``N/A`` literal is treated case-sensitively -- callers must not normalise
  case when comparing against it.

This module has **no GitHub API dependency** so it is fully unit-testable
offline; the thin GitHub-side adapter (comments, labels, reopen) lives in the
guard modules that call it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NO_RESPONSE = "_No response_"

_HEADING_RE = re.compile(r"^### (?P<heading>.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Section:
    """A single ``### heading`` section of a rendered issue body."""

    heading: str
    content: str
    present: bool


def find_section(body: str, heading: str) -> str | None:
    """Return the trimmed content of a ``### heading`` section, or ``None`` if
    the heading does not appear in the body at all.

    A present-but-blank section (GitHub renders ``_No response_`` for an
    unanswered optional field) returns that literal string, not ``None`` --
    callers that want to treat it as "absent" must check for it explicitly via
    :func:`is_no_response`.
    """
    pattern = re.compile(
        rf"^### {re.escape(heading)}\n\n(.*?)(?=\n### |\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(body)
    if match is None:
        return None
    return match.group(1).strip()


def is_no_response(section_content: str | None) -> bool:
    """True when the section is absent, empty, or the literal GitHub
    placeholder for an unanswered optional field."""
    if section_content is None:
        return True
    return section_content.strip() in ("", _NO_RESPONSE)


def is_na(section_content: str | None) -> bool:
    """Case-sensitive check for the literal ``N/A`` token (E01-D01 §5)."""
    return section_content is not None and section_content.strip() == "N/A"


# Repository transferred to the CandleViewer organisation on 2026-10-19; GitHub redirects the old
# path. Evidence links written before the transfer still name the old owner, so they count for the
# same repository name (the repository name must still match).
LEGACY_OWNERS: tuple[str, ...] = ("basiltt",)

_ACTIONS_RUN_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/\d+(?:/jobs/\d+)?/?$"
)


def find_repo_actions_run_urls(text: str, owner: str, repo: str) -> list[str]:
    """Return every URL in ``text`` that points at an Actions run for
    ``owner/repo`` specifically (not an arbitrary external link, and not an
    Actions run belonging to a different repository).

    ``LEGACY_OWNERS`` are aliases of ``owner`` for the same ``repo`` name, so run
    links written before the 2026-10-19 transfer stay valid."""
    if not text:
        return []
    candidates = re.findall(r"https?://\S+", text)
    matches: list[str] = []
    for candidate in candidates:
        candidate = candidate.rstrip(").,]>\"'")
        m = _ACTIONS_RUN_URL_RE.match(candidate)
        if m and m.group("repo") == repo and m.group("owner") in (owner, *LEGACY_OWNERS):
            matches.append(candidate)
    return matches


# --- Sign-off / deviation markers -----------------------------------------

QA_SIGNOFF_MARKER_RE = re.compile(r"QA sign-off:\s*(pass|fail)\b", re.IGNORECASE)
QA_DEVIATION_MARKER_RE = re.compile(r"QA capacity deviation", re.IGNORECASE)
# CandleViewer is a single-owner, user-level repo (`CandleViewer/CandleViewer`,
# ADR-0017) -- there is no GitHub org and so no `@CandleViewer/security` team
# to check membership of. A security sign-off must therefore carry this
# explicit marker (mirroring QA_SIGNOFF_MARKER_RE) so *any* comment from
# someone with write access cannot be read as an implicit approval.
SECURITY_SIGNOFF_MARKER_RE = re.compile(r"Security sign-off:\s*(pass|fail)\b", re.IGNORECASE)

GOV_BOT_MARKER_PREFIX = "<!-- gov-bot:"


def gov_bot_marker(guard_name: str) -> str:
    """The HTML-comment marker this workflow's own comments are tagged with,
    so a later run can find and edit its own prior comment instead of
    spamming a new one (idempotent re-run requirement)."""
    return f"<!-- gov-bot:{guard_name} -->"
