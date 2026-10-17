"""The E27 accounts pack resolver, bound to this checkout's pack, for the test tree (E27-Q01, #833).

The resolver is `cvdev.account_fixture.pack` (#2893 S5): dev-only code that a running stack serves
from too, so no second copy can drift. This module binds it to `packages/fixtures/accounts` and
keeps the names the pack tests import.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Final

from cvdev.account_fixture import pack as resolver
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
schema = partial(resolver.schema, PACK)
scenario_names = partial(resolver.scenario_names, PACK)
manifest = partial(resolver.manifest, PACK)
load = partial(resolver.load, PACK)
load_rotation = partial(resolver.load_rotation, PACK)
_payload = partial(resolver._payload, PACK)
