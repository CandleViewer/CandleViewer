"""E42-Q03 (#1216): the admin performance harness (the dataset driver and the runner).

`datasets.py` loads AUDIT-10M into its own test database through the fixture loaders; `run.py`
runs the k6 profiles against the API on that database and judges them. Both check their targets
with `tests/load/admin/guard.py` before anything connects. The plan is `qa/plans/e42-perf-chaos.md`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

REPO: Final = Path(__file__).resolve().parents[4]
HARNESS: Final = REPO / "tests" / "load" / "admin"


def load_harness(name: str) -> ModuleType:
    """A module of `tests/load/admin` (outside this package), by path; cached in `sys.modules`."""
    qualified = f"cv_admin_harness_{name}"
    if qualified in sys.modules:
        return sys.modules[qualified]
    spec = importlib.util.spec_from_file_location(qualified, HARNESS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"tests/load/admin/{name}.py is missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module
