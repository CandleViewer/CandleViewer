"""Codegen driver: pydantic v2 models from docs/plan/22-api-openapi.yaml (REST)
and docs/plan/ws-schema.json (WS) into
services/api/candleviewer/api/_generated/ and
services/api/candleviewer/ws/_generated/ (E02-T09).

Wraps `datamodel-code-generator` (pinned in pyproject.toml [dependency-groups]
dev) and post-processes the output so money/size/price fields (convention C6)
generate as a `Decimal`-backed type instead of a bare `str` RootModel — the
generator has no native "this string is money" concept, so we patch it here
rather than accept float/str drift on the backend. That type enforces the contract's `Decimal`
pattern on the raw input, and a member the contract defaults and does not mark nullable refuses
`null` (`--strict-nullable`): the generated models are no laxer than the contract (#906 slice G).

It also writes `candleviewer/api/_generated/contract_subset.json` (#2555): the pruned copy of
the REST contract that the app reads at runtime, since the API image ships no `docs/plan`.
`render_contract_subset` in `candleviewer/api/contract_conformance.py` defines its content. The
artifact records no digest of the YAML (#2743), so two PRs that change different parts of the
contract do not conflict on it: `--check` here and the always-on `gen` CI gate
(`tools/ci/check_gen_freshness.py`) render it again and compare, which catches a YAML edit that
skipped regeneration and a hand edit of the artifact alike.

Usage: uv run python scripts/generate_protocol_models.py [--check]
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_SPEC = REPO_ROOT / "docs" / "plan" / "22-api-openapi.yaml"
WS_SCHEMA = REPO_ROOT / "docs" / "plan" / "ws-schema.json"

REST_OUT = SERVICE_ROOT / "candleviewer" / "api" / "_generated" / "openapi_models.py"
WS_OUT = SERVICE_ROOT / "candleviewer" / "ws" / "_generated" / "ws_models.py"
CONTRACT_OUT = SERVICE_ROOT / "candleviewer" / "api" / "_generated" / "contract_subset.json"
CONTRACT_BUILDER = SERVICE_ROOT / "candleviewer" / "api" / "contract_conformance.py"

HEADER_MARKER = "GENERATED FILE — DO NOT EDIT BY HAND"

REST_HEADER = f'''"""{HEADER_MARKER}.

Regenerate with `uv run --project services/api python scripts/generate_protocol_models.py`.
Source: docs/plan/22-api-openapi.yaml, via datamodel-code-generator.
"""

'''

WS_HEADER = f'''"""{HEADER_MARKER}.

Regenerate with `uv run --project services/api python scripts/generate_protocol_models.py`.
Source: docs/plan/ws-schema.json (extracted from docs/plan/23-ws-protocol.md
§13-15 by packages/protocol/scripts/extract-ws-schema.mjs), via
datamodel-code-generator.
"""

'''

# Each model package's __init__.py, written only when it is missing. `--check` compares the
# models and the subset, not these, so a test pins the committed copies to this text (#3392).
PACKAGE_INIT = '"""Generated model package (E02-T09). Never hand-edit."""\n'

# Matches the generated `class Decimal(RootModel[str]): ...` block emitted for
# the OpenAPI/JSON-Schema `Decimal` primitive (money/size/price, convention C6).
_DECIMAL_ROOTMODEL_RE = re.compile(
    r"class Decimal\(RootModel\[str\]\):\n(?:[ \t].*\n)+",
)
# The `pattern="..."` literal inside that block: the contract's own `Decimal` pattern.
_DECIMAL_PATTERN_RE = re.compile(r'pattern=("(?:[^"\\]|\\.)*")')

# What replaces the block. The pattern is checked before anything converts the input, so a bad
# string is a `ValueError` (a 422), never an `InvalidOperation` (a 500), and an exponent string is
# never converted. `fullmatch`, not `match`: Python's `$` also matches before a trailing newline.
_C6_DECIMAL_SOURCE = '''\
_C6_DECIMAL = re.compile(__C6_PATTERN__)


def _c6_decimal(value: object) -> _StdlibDecimal:
    """Convention C6: a decimal on the wire is a string that fully matches the contract's
    `Decimal` pattern, checked before any conversion. Trusted code may pass a `Decimal`; the
    `Decimal` validation that follows refuses a non-finite one."""
    if isinstance(value, _StdlibDecimal):
        return value
    if isinstance(value, str) and _C6_DECIMAL.fullmatch(value):
        return _StdlibDecimal(value)
    raise ValueError(f"must be a decimal string matching {_C6_DECIMAL.pattern} (convention C6)")


Decimal = Annotated[
    _StdlibDecimal,
    PlainSerializer(lambda d: format(d, "f"), return_type=str),
    BeforeValidator(_c6_decimal),
]
"""Arbitrary-precision decimal (convention C6): serialises as a JSON/YAML
string on the wire, but is a real `decimal.Decimal` in Python — money and
size/price fields must never round-trip through float."""
'''


def _run_datamodel_codegen(*, input_path: Path, input_file_type: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    init_file = output_path.parent / "__init__.py"
    if not init_file.exists():
        init_file.write_text(PACKAGE_INIT, encoding="utf-8")

    cmd = [
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(input_path),
        "--input-file-type",
        input_file_type,
        "--output",
        str(output_path),
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--target-python-version",
        "3.12",
        "--use-annotated",
        "--field-constraints",
        # A member the contract defaults and does not mark nullable is `X = default`, not
        # `X | None = default`: omitted it takes the default, but `null` is refused.
        "--strict-nullable",
        "--collapse-root-models",
        "--enum-field-as-literal",
        "all",
        "--disable-timestamp",
        "--use-double-quotes",
        "--formatters",
        "black",
        "isort",
    ]
    subprocess.run(  # noqa: S603 — fixed argv, no shell, trusted cmd
        cmd, cwd=SERVICE_ROOT, check=True
    )


def _strip_generator_banner(source: str) -> str:
    lines = source.splitlines(keepends=True)
    out = []
    skipping = True
    for line in lines:
        if skipping and line.startswith("#"):
            continue
        skipping = False
        out.append(line)
    return "".join(out).lstrip("\n")


def _patch_decimal_money_type(source: str) -> str:
    """Replaces the generated `Decimal(RootModel[str])` wrapper with a real
    `decimal.Decimal`-backed annotated type, per convention C6: money/size/price
    fields must never round-trip through float, and `Decimal` should mean the
    stdlib type everywhere it is referenced in the generated module.

    Its `BeforeValidator` enforces the `Decimal` pattern read from the block it replaces.
    """
    if "class Decimal(RootModel[str]):" not in source:
        # No money fields in this document (e.g. a WS schema subset) — nothing to patch.
        return source

    block = _DECIMAL_ROOTMODEL_RE.search(source)
    if block is None:
        raise RuntimeError(
            "generate_protocol_models: found the Decimal RootModel marker but the "
            "replace regex did not match — datamodel-code-generator's output shape "
            "changed; update _DECIMAL_ROOTMODEL_RE."
        )
    pattern = _DECIMAL_PATTERN_RE.search(block.group(0))
    if pattern is None:
        raise RuntimeError(
            "generate_protocol_models: the Decimal RootModel carries no pattern, so there is "
            "no C6 pattern for the validator to enforce — restore `pattern` on the contract's "
            "`Decimal` schema, or update _DECIMAL_PATTERN_RE."
        )
    replacement = _C6_DECIMAL_SOURCE.replace("__C6_PATTERN__", pattern.group(1))
    patched = source[: block.start()] + replacement + source[block.end() :]

    # Add the extra imports the replacement needs, right after the pydantic import block.
    stdlib_imports = "import re\nfrom decimal import Decimal as _StdlibDecimal\n\n"
    import_block = stdlib_imports + "from pydantic import BeforeValidator, PlainSerializer\n"
    marker = "from pydantic import (\n"
    if marker in patched:
        # Insert BeforeValidator/PlainSerializer into the existing pydantic import
        # tuple instead of a second `from pydantic import` line, so isort/ruff
        # never has to dedupe on a subsequent regen.
        patched = patched.replace(marker, stdlib_imports + marker, 1)
        for name in ("BeforeValidator", "PlainSerializer"):
            if f"    {name},\n" not in patched:
                patched = patched.replace(marker, marker + f"    {name},\n", 1)
    else:
        patched = patched.replace(
            "from pydantic import",
            import_block.rstrip("\n") + "\nfrom pydantic import",
            1,
        )
    return patched


def _write(path: Path, header: str, source: str) -> None:
    body = _strip_generator_banner(source)
    body = _patch_decimal_money_type(body)
    path.write_text(header + body, encoding="utf-8", newline="\n")


def _contract_builder() -> ModuleType:
    """`candleviewer/api/contract_conformance.py`, loaded by file path. Importing it as
    `candleviewer.api.contract_conformance` would first run `candleviewer/api/__init__.py`,
    which imports every router; the module itself needs only the stdlib at import."""
    spec = importlib.util.spec_from_file_location("_cv_contract_builder", CONTRACT_BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"generate_protocol_models: cannot load {CONTRACT_BUILDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate() -> None:
    _run_datamodel_codegen(input_path=OPENAPI_SPEC, input_file_type="openapi", output_path=REST_OUT)
    raw_rest = REST_OUT.read_text(encoding="utf-8")
    _write(REST_OUT, REST_HEADER, raw_rest)

    _run_datamodel_codegen(input_path=WS_SCHEMA, input_file_type="jsonschema", output_path=WS_OUT)
    raw_ws = WS_OUT.read_text(encoding="utf-8")
    _write(WS_OUT, WS_HEADER, raw_ws)

    subset = _contract_builder().render_contract_subset(OPENAPI_SPEC.read_bytes())
    CONTRACT_OUT.write_text(subset, encoding="utf-8", newline="\n")


def check() -> None:
    """Regenerates into a temp copy and diffs against the committed files
    (the `make gen && git diff --exit-code` pattern, run in-process). Byte equality, so a
    hand edit of any of the three outputs fails it as surely as a contract edit that skipped
    regeneration."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        saved_rest = REST_OUT.read_bytes() if REST_OUT.exists() else None
        saved_ws = WS_OUT.read_bytes() if WS_OUT.exists() else None
        saved_contract = CONTRACT_OUT.read_bytes() if CONTRACT_OUT.exists() else None
        try:
            generate()
            rest_after = REST_OUT.read_bytes()
            ws_after = WS_OUT.read_bytes()
            contract_after = CONTRACT_OUT.read_bytes()
        finally:
            if saved_rest is not None:
                REST_OUT.write_bytes(saved_rest)
            if saved_ws is not None:
                WS_OUT.write_bytes(saved_ws)
            if saved_contract is not None:
                CONTRACT_OUT.write_bytes(saved_contract)
            else:
                CONTRACT_OUT.unlink(missing_ok=True)

        stale = []
        if saved_rest != rest_after:
            stale.append(str(REST_OUT))
        if saved_ws != ws_after:
            stale.append(str(WS_OUT))
        if saved_contract != contract_after:
            stale.append(str(CONTRACT_OUT))
        if stale:
            print(
                "[generate_protocol_models --check] stale generated file(s): "
                + ", ".join(stale)
                + " — run "
                + "`uv run --project services/api python scripts/generate_protocol_models.py`.",
                file=sys.stderr,
            )
            sys.exit(1)
        print("[generate_protocol_models --check] OK — generated models match the contracts.")
        del tmp_path  # unused beyond context management


def main() -> None:
    if "--check" in sys.argv[1:]:
        check()
    else:
        generate()
        print(f"[generate_protocol_models] wrote {REST_OUT}, {WS_OUT} and {CONTRACT_OUT}.")


if __name__ == "__main__":
    main()
