"""Pins scripts/check-branch-name.mjs to the CONSTITUTION.md C-4.4 type table.

The hook is exercised through its CLI (exit code) so the real allow-list is
what is tested. No network, no git state: a branch name is always passed
explicitly.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "scripts" / "check-branch-name.mjs"

# Types documented outside the C-4.4 table that the hook must also accept:
# `hotfix/` is defined by docs/plan/01-sdlc-and-branching.md section 6.1.
EXTRA_TYPES = {"hotfix"}
# Names the Constitution table does not cover but the hook never rejects.
NON_TYPE_PREFIXES = ("release/", "train/")


def constitution_types() -> set[str]:
    text = (ROOT / "CONSTITUTION.md").read_text(encoding="utf-8")
    start = text.index("**C-4.4**")
    end = text.index("**C-4.5**")
    section = text[start:end]
    return set(re.findall(r"^\| `([a-z]+)/` \|", section, flags=re.MULTILINE))


def hook_accepts(branch: str) -> bool:
    proc = subprocess.run(["node", str(HOOK), branch], capture_output=True, text=True, check=False)
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode == 0


def hook_types() -> set[str]:
    src = HOOK.read_text(encoding="utf-8")
    match = re.search(r"const ALLOWED_PREFIXES = \[(.*?)\];", src, flags=re.DOTALL)
    assert match is not None, "ALLOWED_PREFIXES constant not found in hook; update hook_types()"
    return set(re.findall(r'"([a-z]+)/"', match.group(1)))


def test_constitution_c44_table_is_parsed_non_empty() -> None:
    assert {"feat", "fix", "chore", "design", "spike", "docs"} <= constitution_types()


def test_hook_prefixes_match_constitution_types_plus_documented_extras() -> None:
    assert hook_types() == constitution_types() | EXTRA_TYPES


@pytest.mark.parametrize("kind", sorted(constitution_types() | EXTRA_TYPES))
def test_hook_accepts_branch_with_each_allowed_type(kind: str) -> None:
    assert hook_accepts(f"{kind}/eng-some-slug")


@pytest.mark.parametrize("kind", sorted(constitution_types() | EXTRA_TYPES))
def test_hook_rejects_each_allowed_type_with_empty_slug(kind: str) -> None:
    assert not hook_accepts(f"{kind}/")


@pytest.mark.parametrize("kind", sorted(constitution_types() | EXTRA_TYPES))
def test_hook_rejects_each_allowed_type_when_uppercase(kind: str) -> None:
    assert not hook_accepts(f"{kind.upper()}/eng-some-slug")


@pytest.mark.parametrize("bad", ["feature/x", "wip/x", "my-work", "", "feat-x"])
def test_hook_rejects_unknown_prefix(bad: str) -> None:
    assert not hook_accepts(bad)


@pytest.mark.parametrize("name", ["main", "release/1.4.0", "train/20261019-1"])
def test_hook_always_allows_protected_and_automation_branches(name: str) -> None:
    assert hook_accepts(name)
