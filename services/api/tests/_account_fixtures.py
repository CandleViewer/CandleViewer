"""The E27 accounts pack resolver, bound to this checkout's pack, for the test tree (E27-Q01, #833).

The resolver is `cvdev.account_fixture.pack` (#2893 S5): dev-only code that a running stack serves
from too, so no second copy can drift. This module binds it to `packages/fixtures/accounts` and
keeps the names the pack tests import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from cvdev.account_fixture.pack import (
    ACCOUNT_PARENTS,
    EGRESS_IP,
    OVERLAY,
    WILDCARD,
    Pack,
    Scenario,
    UnstubbedCall,
    merge_patch,
)

__all__ = [
    "ACCOUNT_PARENTS",
    "EGRESS_IP",
    "OVERLAY",
    "PACK_ROOT",
    "WILDCARD",
    "Scenario",
    "UnstubbedCall",
    "_payload",
    "load",
    "load_rotation",
    "manifest",
    "merge_patch",
    "scenario_names",
    "schema",
]

PACK_ROOT: Final = Path(__file__).resolve().parents[3] / "packages" / "fixtures" / "accounts"
PACK: Final = Pack(PACK_ROOT)
schema = PACK.schema
scenario_names = PACK.scenario_names
manifest = PACK.manifest
load = PACK.load
load_rotation = PACK.load_rotation
_payload = PACK.payload
