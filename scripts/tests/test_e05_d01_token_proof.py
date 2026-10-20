"""pytest wrapper for the E05-D01 token-proof verifier.

Runs packages/ui/tokens/tests/verify_tokens.py as a subprocess so the same
check that gates local/manual verification also runs under `pytest`, per
CLAUDE.md/AGENTS.md test-first requirement for any new script.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "packages" / "ui" / "tokens" / "tests" / "verify_tokens.py"


def test_token_proof_all_themes_resolve_with_no_unset_variables() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "OK:" in result.stdout


def _verify_tokens() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_tokens", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_label_on_fill_unresolved_token_fails_its_checks_and_keeps_the_rest() -> None:
    """#3896: a missing or malformed matrix token fails by name; the other findings still print."""
    vt = _verify_tokens()
    every = {**vt.load(vt.PRIMITIVES), **vt.merged_set(vt.THEMES["dark"])}
    dark = {name: vt.resolve(entry["$value"], every) for name, entry in every.items()}
    del dark["color.action.selected"]
    dark["color.border.selected"] = "#4A86EG"  # seven characters, not hex
    dark["color.action.primary.hover"] = "#AFB8F8"  # a tint under the white label

    found = vt.label_on_fill_failures("dark", dark)

    assert "[dark] label-on-fill: color.action.selected is not an opaque hex colour" in found
    assert "[dark] label-on-fill: color.border.selected is not an opaque hex colour" in found
    assert (
        "[dark] primary.hover label: color.text.on-action on color.action.primary.hover 1.903 < 4.5"
        in found
    )
    assert len(found) == len(set(found)) == 3


def test_label_on_fill_thresholds_below_the_wcag_floors_fail() -> None:
    vt = _verify_tokens()
    thresholds = json.loads(vt.LABEL_ON_FILL.read_text(encoding="utf-8"))["thresholds"]

    assert vt.label_on_fill_threshold_failures(thresholds) == []
    assert vt.label_on_fill_threshold_failures({**thresholds, "label": 3, "stateHue": 30}) == [
        "label-on-fill threshold label is 3, below the floor 4.5",
        "label-on-fill threshold stateHue is 30, above 10",
    ]
