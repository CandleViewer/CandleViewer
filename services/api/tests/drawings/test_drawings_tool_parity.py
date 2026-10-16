"""E14-T01 decision record 1: one tool vocabulary - the OpenAPI `DrawingTool` enum, the server
`TOOLS` literal and the `dr_tool` CHECK of migration 0021 are the same 25 names, same order.

Passes once the closed drawings contract (#2380, 25 tools incl. `anchored_vwap`) is in the base.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.drawings_models import TOOLS

_MIGRATION = (
    Path(__file__).resolve().parents[2] / "candleviewer/migrations/versions/0021_drawings.py"
)


def _migration_tools() -> list[str]:
    """The `dr_tool` list in the DDL the migration executes verbatim (`op.execute`)."""
    spec = importlib.util.spec_from_file_location("_m0021_drawings", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check = re.search(r"CONSTRAINT dr_tool CHECK \(tool IN \((.*?)\)\)", module._DRAWINGS_SQL, re.S)
    assert check is not None, "dr_tool CHECK not found in 0021_drawings"
    return re.findall(r"'([a-z_]+)'", check.group(1))


def test_drawing_tool_vocabulary_is_one_list_in_contract_server_and_database() -> None:
    schema = load_openapi_spec()["components"]["schemas"].get("DrawingTool", {})
    contract = schema.get("enum")
    assert contract is not None, "no DrawingTool enum: the closed drawings contract is not merged"
    assert len(TOOLS) == 25
    assert list(TOOLS) == contract, "OpenAPI DrawingTool drifted from drawings_models.TOOLS"
    assert list(TOOLS) == _migration_tools(), "0021 dr_tool drifted from drawings_models.TOOLS"
