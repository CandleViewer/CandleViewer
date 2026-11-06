"""E10-T05 (#5211, BQ-8): the server's keymap vocabulary is fresh, byte for byte.

`api/_generated/hotkey_vocabulary.json` is the data `/settings/hotkeys` judges a profile by: the API
image holds `services/api/candleviewer` alone, so it cannot read `keymap.json`. These tests render
it again with the generator's own code (`scripts/keymap_lint.py --vocabulary`, loaded by path) and
compare bytes, as the governance job's `--check-vocabulary` does, so a keymap, reserved-key or
scope-table change that skipped `make gen` fails in the py lane too. They also pin what it derives
to the client: the keys the locked commands keep are `validate.ts`'s `PERMANENT`.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

_REPO = Path(__file__).resolve().parents[5]
_VOCABULARY = _REPO / "services/api/candleviewer/api/_generated/hotkey_vocabulary.json"
_VALIDATE = _REPO / "apps/web/src/keymap/validate.ts"


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("keymap_lint", _REPO / "scripts/keymap_lint.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LINT = _generator()


def _doc() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(_VOCABULARY.read_text(encoding="utf-8"))
    return loaded


def test_the_vocabulary_is_what_the_generator_renders_from_its_sources_now() -> None:
    keymap = _LINT.KEYMAP.read_bytes()
    rendered = _LINT.render_vocabulary(
        json.loads(keymap), _LINT.API_SPEC.read_text(encoding="utf-8"), keymap,
        _LINT.RESERVED_FILE.read_bytes(),
    )  # fmt: skip
    assert _LINT.VOCABULARY_OUT == _VOCABULARY
    assert _VOCABULARY.read_bytes() == rendered.encode("utf-8"), (
        "hotkey_vocabulary.json is stale: run `python scripts/keymap_lint.py --vocabulary` "
        "(or `make gen`) and commit the result"
    )


def test_the_vocabulary_holds_lf_line_endings_and_names_its_sources() -> None:
    raw = _VOCABULARY.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"}\n")
    assert [source["path"] for source in _doc()["sources"]] == [
        "apps/web/src/keymap/keymap.json",
        "apps/web/src/keymap/reserved-keys.json",
        "docs/plan/22-api-openapi.yaml#HotkeyBinding.scope",
    ]


def test_the_permanently_reserved_keys_are_validate_ts_permanent() -> None:
    """Derived from the locked commands' defaults (BQ-8), pinned to the client's own map."""
    source = _VALIDATE.read_text(encoding="utf-8")
    found = re.search(r"const PERMANENT = new Map<string, string>\(\[(.*?)\]\);", source, re.S)
    assert found is not None, "validate.ts declares no PERMANENT map"
    client = re.findall(r'^\s*\["([^"]+)",', found.group(1), re.M)
    assert sorted(client) == _doc()["permanent_keys"] == ["Ctrl+K", "Esc"]
