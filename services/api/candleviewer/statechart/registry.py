"""services/api/candleviewer/statechart/registry.py — E50-T01.

The single loader for the chart-JSON contract (ADR-0016 Part 1). Validates a
chart *before* `cv.statechart.factory` ever calls `create_machine` on it:

1. JSON-Schema (2020-12) structural validation (`schema.py`).
2. The recursive `KNOWN_MACHINE_KEYS` walk, CV-C57 (`keys.py`) — including
   inline `invoke.src` machine definitions, the one gap the upstream
   library's own recursive check leaves open.
3. Absolute-target resolution (`targets.py`) — belt-and-braces ahead of the
   library's own `strictTargets`.

`registry.py` never imports `xstate_statemachine` (CV-LINT-IMPORT enforces
this from outside; `tools/lint_statecharts.py` fails CI if it ever does).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from candleviewer.statechart.errors import (
    DuplicateMachineKeyError,
    MachineNotFoundError,
    MachineSchemaError,
    UnknownKeyError,
    UnresolvedTargetError,
)
from candleviewer.statechart.keys import find_unknown_keys
from candleviewer.statechart.schema import MACHINE_SCHEMA, canonical_json
from candleviewer.statechart.targets import find_target_findings

DEFAULT_MACHINES_DIR = Path(__file__).resolve().parent / "machines"


def _jsonschema_validate(chart: dict[str, Any], machine_id: str) -> None:
    """Structural validation against `MACHINE_SCHEMA` (2020-12)."""
    import jsonschema

    validator_cls = jsonschema.Draft202012Validator
    validator_cls.check_schema(MACHINE_SCHEMA)
    validator = validator_cls(MACHINE_SCHEMA)
    errors = sorted(validator.iter_errors(chart), key=lambda e: list(e.path))
    if errors:
        lines = [f"  {'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise MachineSchemaError(
            f"Machine '{machine_id}' failed schema validation:\n" + "\n".join(lines)
        )


def validate(chart: dict[str, Any]) -> None:
    """Run every registry-side check on *chart*, raising on the first family
    that fails (schema, then CV-C57 keys, then targets) so one clear error
    class reaches the caller rather than a mixed bag."""
    machine_id = str(chart.get("id", "<machine>"))
    _jsonschema_validate(chart, machine_id)

    key_findings = find_unknown_keys(chart)
    if key_findings:
        raise UnknownKeyError(
            f"Machine '{machine_id}' has unknown key(s) (CV-C57):\n"
            + "\n".join(f"  {f}" for f in key_findings)
        )

    target_findings = find_target_findings(chart)
    if target_findings:
        raise UnresolvedTargetError(
            f"Machine '{machine_id}' has unresolvable transition target(s):\n"
            + "\n".join(f"  {f}" for f in target_findings)
        )


def machine_hash(chart: dict[str, Any]) -> str:
    """`sha256(canonical_json(chart))`, hex-encoded (ticket criterion 3:
    stable under key reordering — `canonical_json` sorts keys)."""
    return hashlib.sha256(canonical_json(chart)).hexdigest()


def export_stately(chart: dict[str, Any]) -> dict[str, Any]:
    """A Stately-Studio-importable projection of *chart*.

    Stately's own JSON import format is (for our subset of features) the
    same shape as the XState v5 chart config we already author, minus our
    CV-prefixed policy keys — which Stately does not know and would ignore
    or warn on. This is a pure, side-effect-free dict transform; callers
    decide whether/where to write it (round-trip tested in
    `tests/unit/statechart/test_registry.py`).
    """
    drop = {
        "strictConfig",
        "strict",
        "strictTargets",
        "actionErrorPolicy",
        "guardErrorPolicy",
        "spawnBlockingTimeout",
    }

    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in drop}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return strip(chart)  # type: ignore[no-any-return]  # dict-in/dict-out, checked above


class Registry:
    """Loads and validates every `machines/*.machine.json` under a directory.

    Construction does the I/O and validation eagerly (`registry.hash(key)`
    and `registry.export_stately(key)` never re-validate), so a bad chart
    fails at registry-build time — the earliest possible point, and well
    before `cv.statechart.factory.build()` is ever called.
    """

    def __init__(self, machines_dir: Path | None = None) -> None:
        self._machines_dir = machines_dir or DEFAULT_MACHINES_DIR
        self._charts: dict[str, dict[str, Any]] = {}
        self._files: dict[str, Path] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self._machines_dir.exists():
            return
        for path in sorted(self._machines_dir.rglob("*.machine.json")):
            chart = json.loads(path.read_text(encoding="utf-8"))
            machine_id = str(chart.get("id", path.stem))
            if machine_id in self._charts:
                raise DuplicateMachineKeyError(
                    f"machine id '{machine_id}' declared in both "
                    f"{self._files[machine_id]} and {path}"
                )
            validate(chart)
            self._charts[machine_id] = chart
            self._files[machine_id] = path

    def keys(self) -> list[str]:
        return sorted(self._charts)

    def get(self, key: str) -> dict[str, Any]:
        try:
            return self._charts[key]
        except KeyError as exc:
            raise MachineNotFoundError(f"no registered machine with id '{key}'") from exc

    def hash(self, key: str) -> str:
        return machine_hash(self.get(key))

    def export_stately(self, key: str) -> dict[str, Any]:
        return export_stately(self.get(key))


_default: Registry | None = None


def default_registry() -> Registry:
    """The process's one `Registry` over the committed charts, loaded on first use (`build()`'s)."""
    global _default
    if _default is None:
        _default = Registry()
    return _default
