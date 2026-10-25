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

import ast
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


# What `--strict-types int` leaves: `StrictInt` in the import tuple, in a root model and in a union.
_INTEGER_BLOCK = """\
from typing import Annotated

from pydantic import (
    BaseModel,
    Field,
    RootModel,
    StrictInt,
)


class Count(RootModel[StrictInt]):
    root: Annotated[StrictInt, Field(ge=0, le=9)]


class Box(BaseModel):
    size: Annotated[StrictInt | None, Field(ge=1, le=9)] = None
"""


def test_the_integer_type_is_a_json_integer() -> None:
    """`StrictInt` refuses `5.0`, which the contract's `type: integer` takes (JSON Schema)."""
    patched = _generator()._patch_json_integer(_INTEGER_BLOCK)
    assert "StrictInt" not in patched
    namespace: dict[str, Any] = {}
    code = compile(patched, "<patched>", "exec", dont_inherit=True)  # annotations evaluated here
    exec(code, namespace)  # noqa: S102 - the generator's own output for a fixed fixture
    adapter: TypeAdapter[Any] = TypeAdapter(namespace["JsonInt"])
    assert [adapter.validate_python(taken) for taken in (5, 5.0)] == [5, 5]
    for refused in ("5", " 5", "5.0", True, False, 5.5, float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            adapter.validate_python(refused)
    assert namespace["Count"].model_validate(9.0).root == 9
    assert namespace["Box"].model_validate({"size": 2.0}).size == 2
    with pytest.raises(ValidationError):  # a bound still applies to a whole float
        namespace["Count"].model_validate(10.0)
    with pytest.raises(ValidationError):
        namespace["Box"].model_validate({"size": 10.0})


def test_a_strict_integer_import_the_patch_cannot_find_stops_the_generator() -> None:
    shared = (
        "from pydantic import BaseModel, StrictInt\n\n\nclass A(BaseModel):\n    n: StrictInt\n"
    )
    with pytest.raises(RuntimeError, match="update _patch_json_integer"):
        _generator()._patch_json_integer(shared)


def test_only_the_rest_run_passes_the_strict_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The WS models hold no scalar member, so `--check` cannot see a WS run that took the flags."""
    gen, runs = _generator(), []

    def fake(
        *, input_file_type: str, output_path: Path, extra: tuple[str, ...] = (), **_: Any
    ) -> None:
        runs.append((input_file_type, extra))
        marked = "--use-missing-sentinel" in extra  # the sentinel run types the member its way
        member = "str | MISSING = MISSING" if marked else "str | None = None"
        output_path.write_text(f"{_BOX_MODULE}    plain: {member}\n", encoding="utf-8")

    monkeypatch.setattr(gen, "_run_datamodel_codegen", fake)
    for name in ("REST_OUT", "WS_OUT", "CONTRACT_OUT"):
        monkeypatch.setattr(gen, name, tmp_path / name)
    gen.generate()
    sentinel = (*gen._STRICT_SCALARS, "--use-missing-sentinel")
    assert runs == [("openapi", gen._STRICT_SCALARS), ("openapi", sentinel), ("jsonschema", ())]


#: A codegen output of one model, whose member each fake run types its own way.
_BOX_MODULE = "from __future__ import annotations\n\n\nclass Box(BaseModel):\n"


def test_a_sentinel_run_that_marks_nothing_stops_the_generator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1S-01: a sentinel run whose shape changed (a renamed `MISSING`, a flag gone quiet) marks no
    member; the generator stops, never writes a module that refuses no `null`."""
    gen = _generator()

    def fake(*, output_path: Path, **_: Any) -> None:
        output_path.write_text(f"{_BOX_MODULE}    plain: str | None = None\n", encoding="utf-8")

    monkeypatch.setattr(gen, "_run_datamodel_codegen", fake)
    for name in ("REST_OUT", "WS_OUT", "CONTRACT_OUT"):
        monkeypatch.setattr(gen, name, tmp_path / name)
    with pytest.raises(RuntimeError, match="marked no member"):
        gen.generate()


# What `--use-missing-sentinel` emits: an optional member with no default is `X | MISSING`.
_SENTINEL_BLOCK = """\
class Box(BaseModel):
    plain: str | MISSING = MISSING
    nullable: str | None | MISSING = MISSING
    anything: Any | MISSING = MISSING
    mapping: dict[str, int | None] | MISSING = MISSING
    bounded: Annotated[int | MISSING, Field(ge=1)] = MISSING
    required: str
    defaulted: int = 1
"""


def test_the_sentinel_run_marks_the_optional_members_that_refuse_null() -> None:
    """`None` or `Any` at the top of a member's union lets it be `null`; inside a `dict`, not."""
    marked = _generator()._null_refused_members(_SENTINEL_BLOCK)
    assert marked == {"Box": ["plain", "mapping", "bounded"]}


# The normal output of five classes, each of which the sentinel run marks one member of.
_NULL_BLOCK = """\
from pydantic import (
    BaseModel,
)
class Parent(BaseModel):
    a: str | None = None
class Child(Parent):
    b: str | None = None
class Shown(Parent):
    c: str | None = None
class Base(BaseModel):
    d: str | None = None
    f: int = 1
class Sent(Base):
    e: str | None = None
"""
_MARKED = {"Parent": ["a"], "Child": ["b"], "Shown": ["c"], "Base": ["d"], "Sent": ["e"]}
_REQUESTED = {"Parent", "Child", "Sent"}


def test_each_marked_class_gets_one_refusal_of_its_own() -> None:
    patched = _generator()._add_null_refusals(_NULL_BLOCK, _MARKED, _REQUESTED)
    assert [line.strip() for line in patched.splitlines() if "= field_validator(" in line] == [
        '__null_refused = field_validator("a", mode="before")(_refuse_null)',
        '__null_refused = field_validator("b", mode="before")(_refuse_null)',
        '_Parent__null_refused = field_validator("a", mode="before")(_take_null)',
        '_Base__null_refused = field_validator("d", mode="before")(_refuse_null)',
        '__null_refused = field_validator("e", mode="before")(_refuse_null)',
    ]


def test_a_subclass_keeps_its_parents_null_refusals() -> None:
    """No request model extends another on this contract, so a fixture shows the mangled names at
    work: `Child` keeps `Parent`'s refusal; `Shown`, which no request body reaches, takes `null`
    again; `Sent` refuses its base's `d`, which `Base` itself takes."""
    namespace: dict[str, Any] = {}
    patched = _generator()._add_null_refusals(_NULL_BLOCK, _MARKED, _REQUESTED)
    code = compile(patched, "<patched>", "exec", dont_inherit=True)
    exec(code, namespace)  # noqa: S102 - the generator's own output for a fixed fixture
    probes = [("Parent", "a"), ("Child", "a"), ("Child", "b"), ("Shown", "a"), ("Shown", "c")]
    probes += [("Base", "d"), ("Sent", "d"), ("Sent", "e")]
    taken = [(name, member) for name, member in probes if _takes_null(namespace[name], member)]
    assert taken == [("Shown", "a"), ("Shown", "c"), ("Base", "d")]


def _takes_null(model: Any, member: str) -> bool:
    try:
        model.model_validate({member: None})
    except ValidationError:
        return False
    return True


@pytest.mark.parametrize(
    ("marked", "says"),
    [({"Gone": ["a"]}, "does not define"), ({"Base": ["f"]}, "not `= None` here")],
    ids=["class", "default"],
)
def test_a_mark_the_models_cannot_hold_stops_the_generator(
    marked: dict[str, list[str]], says: str
) -> None:
    """Each disagreement between the two runs stops the generator with its own message (R1C-03)."""
    with pytest.raises(RuntimeError, match=f"{says}; update _null_refused_members"):
        _generator()._add_null_refusals(_NULL_BLOCK, marked, _REQUESTED)


def test_a_module_without_the_pydantic_import_tuple_stops_the_generator() -> None:
    source = "from pydantic import BaseModel\nclass Box(BaseModel):\n    a: str | None = None\n"
    with pytest.raises(RuntimeError, match="no pydantic import tuple"):
        _generator()._add_null_refusals(source, {"Box": ["a"]}, {"Box"})


def test_a_refusal_lands_after_its_class_whatever_its_text_holds() -> None:
    """Only `\\n` ends a line for the tokenizer: a U+2028 in a docstring does not move the
    refusal into the brackets of the class's last member (R1C-02)."""
    source = (
        "from pydantic import (\n    BaseModel,\n)\nclass Box(BaseModel):\n"
        '    """One\u2028two."""\n    a: (\n        str | None\n    ) = None\n'
    )
    patched = _generator()._add_null_refusals(source, {"Box": ["a"]}, {"Box"})
    box = next(n for n in ast.parse(patched).body if isinstance(n, ast.ClassDef))
    assert [ast.unparse(m.targets[0]) for m in box.body if isinstance(m, ast.Assign)] == [
        "__null_refused"
    ]


def test_the_request_walk_follows_a_shared_body_and_a_bases_members() -> None:
    """A `requestBodies` entry's schema is a root, and what a reached class's base names is
    reached through the subclass (R1C-05)."""
    body = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Child"}}}}
    spec = {
        "paths": {"/x": {"post": {"requestBody": {"$ref": "#/components/requestBodies/Shared"}}}},
        "components": {"requestBodies": {"Shared": body}},
    }
    source = (
        "class Held(BaseModel):\n    x: int\nclass Base(BaseModel):\n    held: Held | None = None\n"
        "class Child(Base):\n    y: int\nclass Other(BaseModel):\n    z: int\n"
    )
    assert _generator()._request_models(spec, source) == {"Child", "Held"}


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
