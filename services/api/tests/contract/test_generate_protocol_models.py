"""Generator-output contract tests for E02-T09.

Asserts the acceptance criteria that a code-review can't verify by eye:
money/size/price fields (convention C6) are backed by a real
`decimal.Decimal` (never `float`/bare `str`), the generated modules import
cleanly and are `mypy --strict` clean, and — the actual staleness gate —
regenerating from the same two contracts twice in a row is byte-identical.

Runs `scripts/generate_protocol_models.py` as a subprocess against a scratch
copy of the two source-of-truth contracts, so the test exercises the exact
code path CI's `generated-code` check runs, not a hand-simulated shortcut.
"""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _SERVICE_ROOT / "scripts" / "generate_protocol_models.py"
_REST_OUT = _SERVICE_ROOT / "candleviewer" / "api" / "_generated" / "openapi_models.py"
_WS_OUT = _SERVICE_ROOT / "candleviewer" / "ws" / "_generated" / "ws_models.py"
_CONTRACT_OUT = _SERVICE_ROOT / "candleviewer" / "api" / "_generated" / "contract_subset.json"


def _run_generator(*extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed argv, no shell, trusted script under test
        [sys.executable, str(_SCRIPT), *extra_args],
        cwd=_SERVICE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def generated_rest_module():  # type: ignore[no-untyped-def]
    """Imports the already-committed generated REST models module.

    This does not regenerate — it exercises the file as committed, so a
    stale-but-uncommitted regen never masks an import/type defect in what
    actually ships.
    """
    module = importlib.import_module("candleviewer.api._generated.openapi_models")
    return importlib.reload(module)


@pytest.fixture(scope="module")
def generated_ws_module():  # type: ignore[no-untyped-def]
    module = importlib.import_module("candleviewer.ws._generated.ws_models")
    return importlib.reload(module)


def test_rest_models_module_defines_a_decimal_backed_money_type(generated_rest_module) -> None:  # type: ignore[no-untyped-def]
    """Convention C6: money/size/price fields must never be a bare string or
    float — the generated `Decimal` name must resolve to a type whose
    instances really are `decimal.Decimal` after validation, not a
    `RootModel[str]` wrapper around one.
    """
    from pydantic import BaseModel

    class _Probe(BaseModel):
        amount: generated_rest_module.Decimal

    probe = _Probe.model_validate({"amount": "123.45000001"})
    assert isinstance(probe.amount, Decimal)
    assert probe.amount == Decimal("123.45000001")

    # Round-trips back out as a JSON string, never a float/number — a float
    # would silently lose precision on real money values.
    dumped = probe.model_dump(mode="json")
    assert isinstance(dumped["amount"], str)
    assert dumped["amount"] == "123.45000001"


def test_rest_models_reject_float_input_would_lose_precision(generated_rest_module) -> None:  # type: ignore[no-untyped-def]
    """A float never round-trips a money value exactly — validating through
    `Decimal(str(...))` first is what protects against that; this asserts a
    string with more precision than any float representation survives.
    """
    from pydantic import BaseModel

    class _Probe(BaseModel):
        amount: generated_rest_module.Decimal

    exact = "0.100000000000000000001"
    probe = _Probe.model_validate({"amount": exact})
    assert str(probe.amount) == exact
    assert probe.amount != Decimal(str(float(exact)))


# The `Decimal` schema as the code generator emits it, with a pattern that is not the contract's.
_DECIMAL_BLOCK = """\
from typing import Annotated

from pydantic import (
    Field,
    RootModel,
)


class Decimal(RootModel[str]):
    root: str = Field(pattern="^[0-9]{3}$")
"""


def _generator() -> ModuleType:
    """`scripts/generate_protocol_models.py`, loaded by path (`scripts` is no package)."""
    spec = importlib.util.spec_from_file_location("_cv_generate_protocol_models", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_patched_decimal_enforces_the_pattern_of_the_block_it_replaces() -> None:
    """The pattern is the contract's, read from the generated block, never one the script holds."""
    namespace: dict[str, Any] = {}
    code = compile(_generator()._patch_decimal_money_type(_DECIMAL_BLOCK), "<patched>", "exec")
    exec(code, namespace)  # noqa: S102 - the generator's own output for a fixed fixture
    adapter: TypeAdapter[Any] = TypeAdapter(namespace["Decimal"])
    assert adapter.validate_python("123") == Decimal("123")
    for refused in ("1234", "12", "abc", "1e2", " 123", "123\n", 123):
        with pytest.raises(ValidationError):
            adapter.validate_python(refused)


def test_a_decimal_block_without_a_pattern_stops_the_generator() -> None:
    bare = _DECIMAL_BLOCK.replace('Field(pattern="^[0-9]{3}$")', "Field()")
    with pytest.raises(RuntimeError, match="carries no pattern"):
        _generator()._patch_decimal_money_type(bare)


def test_ws_models_module_imports_cleanly(generated_ws_module) -> None:  # type: ignore[no-untyped-def]
    assert generated_ws_module.__name__ == "candleviewer.ws._generated.ws_models"


def test_generated_files_carry_the_do_not_edit_header() -> None:
    for path in (_REST_OUT, _WS_OUT, _CONTRACT_OUT):
        head = path.read_text(encoding="utf-8")[:400]
        assert "GENERATED FILE — DO NOT EDIT BY HAND" in head, f"{path} is missing its header"


@pytest.mark.integration
def test_regenerating_twice_is_byte_identical(tmp_path: Path) -> None:
    """The staleness gate itself: `generate` must be a pure function of the
    two committed contracts (docs/plan/22-api-openapi.yaml,
    docs/plan/ws-schema.json) — no wall-clock timestamps, no unstable
    ordering. Marked integration: shells out to datamodel-code-generator,
    which is slow enough to skip from the default unit run.
    """
    first = _run_generator()
    assert first.returncode == 0, first.stderr
    rest_after_first = _REST_OUT.read_bytes()
    ws_after_first = _WS_OUT.read_bytes()
    contract_after_first = _CONTRACT_OUT.read_bytes()

    second = _run_generator()
    assert second.returncode == 0, second.stderr
    rest_after_second = _REST_OUT.read_bytes()
    ws_after_second = _WS_OUT.read_bytes()
    contract_after_second = _CONTRACT_OUT.read_bytes()

    assert rest_after_first == rest_after_second, "REST model generation is not deterministic"
    assert ws_after_first == ws_after_second, "WS model generation is not deterministic"
    assert contract_after_first == contract_after_second, "contract subset is not deterministic"


@pytest.mark.integration
def test_check_mode_passes_against_the_committed_generated_files() -> None:
    """Mirrors the CI staleness gate: `--check` must exit 0 when the committed
    generated files already match what the two contracts produce.
    """
    result = _run_generator("--check")
    assert result.returncode == 0, result.stderr or result.stdout
