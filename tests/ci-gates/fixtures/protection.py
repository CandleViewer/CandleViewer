"""E03-Q01 fixture: CI-PROT-002 (required check renamed, silently dropped
from branch protection). Drives the real reconciliation logic in
`scripts/check_required_check_reconciliation.py` against scratch
desired-state / workflow inputs — no repository files are touched.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_spec = importlib.util.spec_from_file_location(
    "check_required_check_reconciliation",
    REPO_ROOT / "scripts" / "check_required_check_reconciliation.py",
)
assert _spec is not None and _spec.loader is not None
_reconcile_mod = importlib.util.module_from_spec(_spec)
sys.modules.setdefault(_spec.name, _reconcile_mod)
_spec.loader.exec_module(_reconcile_mod)

_CONSTITUTION_NAMES = [
    "lint",
    "typecheck",
    "unit-backend",
    "coverage-thresholds",
    "contract",
]


def _desired_state(contexts: list[str]) -> dict[str, object]:
    return {
        "required_status_checks": {"checks": [{"context": c, "app_id": 15368} for c in contexts]},
        "pending_checks": {n: "fixture" for n in _CONSTITUTION_NAMES if n not in contexts},
    }


def build_clean_fixture() -> tuple[bool, str]:
    """All C-9.1 names are accounted for in contexts/pending; no job-name
    mismatch. Expected: reconcile() returns no errors."""
    desired = _desired_state(
        ["lint", "typecheck", "unit-backend", "coverage-thresholds", "contract"]
    )
    job_names = {"lint", "typecheck", "unit-backend", "coverage-thresholds", "contract"}
    errors = _reconcile_mod.reconcile(desired, _CONSTITUTION_NAMES, job_names)
    return (len(errors) == 0, f"{len(errors)} error(s): {errors}")


def build_drift_fixture() -> tuple[bool, str]:
    """CI-PROT-002: `coverage-thresholds` is renamed to `coverage-check` in
    the workflow job names but `branch-protection.json` still requires the
    old name — the mismatch must be detected, not silently dropped."""
    desired = _desired_state(
        ["lint", "typecheck", "unit-backend", "coverage-thresholds", "contract"]
    )
    job_names = {"lint", "typecheck", "unit-backend", "coverage-check", "contract"}
    errors = _reconcile_mod.reconcile(desired, _CONSTITUTION_NAMES, job_names)
    ok = any("coverage-thresholds" in e and "no check run named" in e for e in errors)
    return (not ok, f"{len(errors)} error(s): {errors}")
