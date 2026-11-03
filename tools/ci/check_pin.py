#!/usr/bin/env python3
"""E50-T57 (ADR-0016, 29-statechart-adoption-plan.md §1.2): the
`xstate-statemachine` runtime pin must stay exact and hash-locked.

MUST-09 orders the pin first: every other E50 ticket imports the library,
so a loose specifier (``~=``/``>=``/``*``/no pin) or a drifted lock hash
would let CI resolve a different wheel than the one ADR-0016 accepted
(tag v0.9.1 = tag object 45bb7f3, which dereferences to commit
801eacdeef5bda2ba24b75f537ae04cc3527747e; wheel sha256
d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162).

Three checks, all required:
  1. ``services/api/pyproject.toml`` declares the dependency as exactly
     ``xstate-statemachine==0.9.1`` (a PEP 508 requirement string in the
     ``[project.dependencies]`` array). Any other specifier operator
     (``~=``, ``>=``, ``<=``, ``!=``, ``===``, bare, or a missing entry)
     fails.
  2. ``services/api/uv.lock`` records the pinned wheel's sha256 exactly as
     ``d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162``
     for the ``xstate-statemachine`` package's wheel entry.
  3. ``.github/workflows/xstate-nightly.yml`` sets ``UPSTREAM_SHA`` to the
     full commit ``801eacdeef5bda2ba24b75f537ae04cc3527747e`` (the commit the
     annotated tag v0.9.1 dereferences to, not the tag object), so the
     nightly's upstream checkout cannot follow a moved tag.

Exit codes: 0 clean, 1 violation found, 2 internal error (bad path / repo
files missing).

Stdlib only (plus ``tomllib``, stdlib since 3.11) — this must run before
any package manager is bootstrapped.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import tomllib

PACKAGE_NAME = "xstate-statemachine"
PINNED_VERSION = "0.9.1"
PINNED_REQUIREMENT = f"{PACKAGE_NAME}=={PINNED_VERSION}"
PINNED_WHEEL_SHA256 = "d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162"
PINNED_UPSTREAM_SHA = "801eacdeef5bda2ba24b75f537ae04cc3527747e"
NIGHTLY_WORKFLOW = Path(".github") / "workflows" / "xstate-nightly.yml"

# Matches the workflow's `UPSTREAM_SHA: <value>` env line (YAML kept stdlib-only).
UPSTREAM_SHA_RE = re.compile(
    r"^\s*UPSTREAM_SHA:\s*[\"']?(?P<sha>[^\s\"'#]*)[\"']?\s*(?:#.*)?$", re.MULTILINE
)

# Matches a PEP 508 requirement string naming the package, capturing the
# specifier that follows the name.
REQUIREMENT_RE = re.compile(
    r"^\s*" + re.escape(PACKAGE_NAME) + r"\s*(?P<specifier>[=~!<>].*?)\s*$"
)


@dataclass(frozen=True)
class Violation:
    path: Path
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.path}: {self.message}"


def _find_dependency_requirement(pyproject: Path) -> str | None:
    """Return the raw requirement string for ``PACKAGE_NAME`` in
    ``[project.dependencies]``, or ``None`` if it is absent."""
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"error: invalid TOML in {pyproject}: {exc}") from exc
    deps = data.get("project", {}).get("dependencies", [])
    matches = [
        dep for dep in deps if isinstance(dep, str) and REQUIREMENT_RE.match(dep)
    ]
    if not matches:
        return None
    if len(matches) > 1:
        # Duplicate entries are themselves a drift signal — surface all of
        # them via the first match's specifier check failing below is not
        # enough; report explicitly.
        return "__DUPLICATE__:" + ", ".join(matches)
    return matches[0]


def check_pyproject(pyproject: Path) -> list[Violation]:
    violations: list[Violation] = []
    if not pyproject.exists():
        return [Violation(pyproject, "file does not exist")]

    requirement = _find_dependency_requirement(pyproject)
    if requirement is None:
        violations.append(
            Violation(
                pyproject,
                f"no '{PACKAGE_NAME}' entry found in [project.dependencies]; "
                f"expected exactly '{PINNED_REQUIREMENT}'",
            )
        )
        return violations

    if requirement.startswith("__DUPLICATE__:"):
        violations.append(
            Violation(
                pyproject,
                f"multiple '{PACKAGE_NAME}' entries in [project.dependencies]: "
                f"{requirement.removeprefix('__DUPLICATE__:')}",
            )
        )
        return violations

    if requirement != PINNED_REQUIREMENT:
        violations.append(
            Violation(
                pyproject,
                f"'{PACKAGE_NAME}' must be pinned as exactly "
                f"'{PINNED_REQUIREMENT}' (banned: ~=, >=, <=, !=, ===, bare, "
                f"or any other version); found '{requirement}'",
            )
        )
    return violations


# uv.lock is TOML, but package entries repeat the `[[package]]` table name,
# which `tomllib` handles fine as a list under `package`. We only need the
# one entry whose `name` matches ours and its wheel hash(es).
def check_lock(uv_lock: Path) -> list[Violation]:
    violations: list[Violation] = []
    if not uv_lock.exists():
        return [Violation(uv_lock, "file does not exist")]

    try:
        data = tomllib.loads(uv_lock.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"error: invalid TOML in {uv_lock}: {exc}") from exc

    packages = data.get("package", [])
    matches = [pkg for pkg in packages if pkg.get("name") == PACKAGE_NAME]

    if not matches:
        violations.append(
            Violation(uv_lock, f"no locked '{PACKAGE_NAME}' package entry found")
        )
        return violations
    if len(matches) > 1:
        violations.append(
            Violation(uv_lock, f"multiple locked '{PACKAGE_NAME}' entries found")
        )
        return violations

    pkg = matches[0]
    locked_version = pkg.get("version")
    if locked_version != PINNED_VERSION:
        violations.append(
            Violation(
                uv_lock,
                f"locked version '{locked_version}' does not match pinned "
                f"version '{PINNED_VERSION}'",
            )
        )

    wheel_hashes = {
        wheel.get("hash", "").removeprefix("sha256:")
        for wheel in pkg.get("wheels", [])
        if isinstance(wheel, dict)
    }
    if PINNED_WHEEL_SHA256 not in wheel_hashes:
        violations.append(
            Violation(
                uv_lock,
                f"locked wheel hash(es) {sorted(wheel_hashes) or '(none)'} do "
                f"not include the pinned hash sha256:{PINNED_WHEEL_SHA256}",
            )
        )
    return violations


def check_workflow(workflow: Path) -> list[Violation]:
    if not workflow.exists():
        return [Violation(workflow, "file does not exist")]
    matches = UPSTREAM_SHA_RE.findall(workflow.read_text(encoding="utf-8"))
    if not matches:
        return [
            Violation(
                workflow,
                "no 'UPSTREAM_SHA:' line found; expected "
                f"'UPSTREAM_SHA: {PINNED_UPSTREAM_SHA}'",
            )
        ]
    if len(matches) > 1 or matches[0] != PINNED_UPSTREAM_SHA:
        return [
            Violation(
                workflow,
                f"UPSTREAM_SHA must be exactly '{PINNED_UPSTREAM_SHA}' "
                f"(tag v0.9.1's commit); found {matches}",
            )
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repo root (default: inferred from this file's location).",
    )
    args = parser.parse_args(argv)

    root: Path = args.root
    pyproject = root / "services" / "api" / "pyproject.toml"
    uv_lock = root / "services" / "api" / "uv.lock"

    workflow = root / NIGHTLY_WORKFLOW

    violations: list[Violation] = []
    violations.extend(check_pyproject(pyproject))
    violations.extend(check_lock(uv_lock))
    violations.extend(check_workflow(workflow))

    if violations:
        print(
            "check_pin.py: xstate-statemachine pin violations found:", file=sys.stderr
        )
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    print(
        f"check_pin.py: OK — '{PINNED_REQUIREMENT}' pinned in pyproject.toml, "
        f"wheel hash sha256:{PINNED_WHEEL_SHA256} present in uv.lock, "
        f"UPSTREAM_SHA {PINNED_UPSTREAM_SHA} in the nightly workflow."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
