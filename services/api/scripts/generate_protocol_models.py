"""Codegen driver: pydantic v2 models from docs/plan/22-api-openapi.yaml (REST)
and docs/plan/ws-schema.json (WS) into
services/api/candleviewer/api/_generated/ and
services/api/candleviewer/ws/_generated/ (E02-T09).

Wraps `datamodel-code-generator` (pinned in pyproject.toml [dependency-groups]
dev) and post-processes the output so money/size/price fields (convention C6)
generate as a `Decimal`-backed type instead of a bare `str` RootModel — the
generator has no native "this string is money" concept, so we patch it here
rather than accept float/str drift on the backend.

It also writes `candleviewer/api/_generated/contract_subset.json` (#2555): the pruned copy of
the REST contract that the app reads at runtime, since the API image ships no `docs/plan`.
`candleviewer.api.contract_conformance.render_contract_subset` defines its content.

Usage: uv run python scripts/generate_protocol_models.py [--check]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from candleviewer.api.contract_conformance import render_contract_subset

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_SPEC = REPO_ROOT / "docs" / "plan" / "22-api-openapi.yaml"
WS_SCHEMA = REPO_ROOT / "docs" / "plan" / "ws-schema.json"

REST_OUT = SERVICE_ROOT / "candleviewer" / "api" / "_generated" / "openapi_models.py"
WS_OUT = SERVICE_ROOT / "candleviewer" / "ws" / "_generated" / "ws_models.py"
CONTRACT_OUT = SERVICE_ROOT / "candleviewer" / "api" / "_generated" / "contract_subset.json"

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

# Matches the generated `class Decimal(RootModel[str]): ...` block emitted for
# the OpenAPI/JSON-Schema `Decimal` primitive (money/size/price, convention C6).
_DECIMAL_ROOTMODEL_RE = re.compile(
    r"class Decimal\(RootModel\[str\]\):\n(?:[ \t].*\n)+",
)


def _run_datamodel_codegen(*, input_path: Path, input_file_type: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    init_file = output_path.parent / "__init__.py"
    if not init_file.exists():
        init_file.write_text(
            '"""Generated model package (E02-T09). Never hand-edit."""\n', encoding="utf-8"
        )

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
    """
    if "class Decimal(RootModel[str]):" not in source:
        # No money fields in this document (e.g. a WS schema subset) — nothing to patch.
        return source

    replacement = (
        "Decimal = Annotated[\n"
        "    _StdlibDecimal,\n"
        '    PlainSerializer(lambda d: format(d, "f"), return_type=str),\n'
        "    BeforeValidator(_StdlibDecimal),\n"
        "]\n"
        '"""Arbitrary-precision decimal (convention C6): serialises as a JSON/YAML\n'
        "string on the wire, but is a real `decimal.Decimal` in Python — money and\n"
        'size/price fields must never round-trip through float."""\n'
    )
    patched = _DECIMAL_ROOTMODEL_RE.sub(replacement, source, count=1)
    if patched == source:
        raise RuntimeError(
            "generate_protocol_models: found the Decimal RootModel marker but the "
            "replace regex did not match — datamodel-code-generator's output shape "
            "changed; update _DECIMAL_ROOTMODEL_RE."
        )

    # Add the extra imports the replacement needs, right after the pydantic import block.
    import_block = (
        "from decimal import Decimal as _StdlibDecimal\n\n"
        "from pydantic import BeforeValidator, PlainSerializer\n"
    )
    marker = "from pydantic import (\n"
    if marker in patched:
        # Insert BeforeValidator/PlainSerializer into the existing pydantic import
        # tuple instead of a second `from pydantic import` line, so isort/ruff
        # never has to dedupe on a subsequent regen.
        patched = patched.replace(
            marker,
            "from decimal import Decimal as _StdlibDecimal\n\n" + marker,
            1,
        )
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


def generate() -> None:
    _run_datamodel_codegen(input_path=OPENAPI_SPEC, input_file_type="openapi", output_path=REST_OUT)
    raw_rest = REST_OUT.read_text(encoding="utf-8")
    _write(REST_OUT, REST_HEADER, raw_rest)

    _run_datamodel_codegen(input_path=WS_SCHEMA, input_file_type="jsonschema", output_path=WS_OUT)
    raw_ws = WS_OUT.read_text(encoding="utf-8")
    _write(WS_OUT, WS_HEADER, raw_ws)

    subset = render_contract_subset(OPENAPI_SPEC.read_bytes())
    CONTRACT_OUT.write_text(subset, encoding="utf-8", newline="\n")


def check() -> None:
    """Regenerates into a temp copy and diffs against the committed files
    (the `make gen && git diff --exit-code` pattern, run in-process)."""
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
