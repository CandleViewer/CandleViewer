"""The E27 accounts pack resolver, for the test tree (E27-Q01, #833).

The resolver moved to the dev-only `cvdev.account_fixture.pack` (#2893 S5), so a running stack can
serve the same scenarios as the tests; this module keeps the names the pack tests import.
"""

from __future__ import annotations

from cvdev.account_fixture.pack import (
    ACCOUNT_PARENTS,
    EGRESS_IP,
    OVERLAY,
    PACK_ROOT,
    WILDCARD,
    Scenario,
    UnstubbedCall,
    _payload,
    load,
    load_rotation,
    manifest,
    merge_patch,
    scenario_names,
    schema,
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
