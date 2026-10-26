#!/usr/bin/env python3
"""E17-T05: generate the error-code enums from the single registry in 22-api-openapi.yaml.

Reads ``x-error-codes`` and ``x-error-codes-ws`` and emits (committed, never hand-edited):

* ``services/api/candleviewer/ws/_generated/error_codes.py``
* ``packages/protocol/src/errorCodes.ts``

Usage: ``python tools/errorcodes/generate.py [--check]``. Deterministic; needs PyYAML.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
OPENAPI = REPO / "docs" / "plan" / "22-api-openapi.yaml"
OUT_PY = REPO / "services" / "api" / "candleviewer" / "ws" / "_generated" / "error_codes.py"
OUT_TS = REPO / "packages" / "protocol" / "src" / "errorCodes.ts"
SRC_NOTE = "docs/plan/22-api-openapi.yaml (x-error-codes, x-error-codes-ws)"


CODE_SHAPE = re.compile(r"[a-z][a-z0-9_]*")


class RegistryError(ValueError):
    """The registry in the OpenAPI document is malformed."""


def load_registry(text: str) -> list[dict[str, Any]]:
    """Normalised, validated entries: REST codes first, then WS-only, source order."""
    doc = yaml.safe_load(text)
    rest = doc.get("x-error-codes")
    ws = doc.get("x-error-codes-ws")
    if not isinstance(rest, list) or not isinstance(ws, list):
        raise RegistryError("x-error-codes and x-error-codes-ws must both be lists")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for origin, block in (("x-error-codes", rest), ("x-error-codes-ws", ws)):
        for raw in block:
            code = str(raw.get("code", "")).strip().lower()
            if not code:
                raise RegistryError(f"{origin}: entry without a code: {raw!r}")
            if code in seen:
                raise RegistryError(f"duplicate error code {code!r} (second seen in {origin})")
            if CODE_SHAPE.fullmatch(code) is None:
                raise RegistryError(
                    f"{origin}: error code {code!r} must match [a-z][a-z0-9_]* "
                    "(codes are emitted unescaped into Python and TypeScript)"
                )
            seen.add(code)
            if origin == "x-error-codes":
                surface = [str(s).strip().lower() for s in raw.get("surface", ["rest"])]
                scope = "any" if "ws" in surface else None
            else:
                surface = ["ws"]
                scope = raw.get("scope")
                if not scope:
                    raise RegistryError(f"{code}: WS code without scope")
            entries.append(
                {
                    "code": code,
                    "surface": surface,
                    "scope": scope,
                    "retryable": bool(raw.get("retryable", False)),
                    "rest_analogue": raw.get("rest_analogue"),
                    "close_code": raw.get("close_code"),
                    "title": str(raw.get("title", "")).strip(),
                }
            )
    return entries


def _py_literal(value: object) -> str:
    """A Python literal for a JSON-shaped scalar: ``None`` for null, never a text replacement."""
    return "None" if value is None else json.dumps(value)


def _member(code: str) -> str:
    return code.upper()


def render_py(entries: list[dict[str, Any]]) -> str:
    out = [
        '"""GENERATED FILE - DO NOT EDIT BY HAND.',
        "",
        "Generator: tools/errorcodes/generate.py (E17-T05).",
        f"Source: {SRC_NOTE}. Edit the YAML and run `make gen`.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from enum import StrEnum",
        "from typing import Final, NamedTuple",
        "",
        "",
        "class ErrorCode(StrEnum):",
    ]
    out += [f'    {_member(e["code"])} = "{e["code"]}"' for e in entries]
    out += [
        "",
        "",
        "class ErrorMeta(NamedTuple):",
        "    surfaces: tuple[str, ...]",
        "    scope: str | None",
        "    retryable: bool",
        "    rest_analogue: str | None",
        "    close_code: int | None",
        "    title: str",
        "",
        "",
        "ERROR_META: Final[dict[ErrorCode, ErrorMeta]] = {",
    ]
    for e in entries:
        surf = "(" + "".join(f'"{s}", ' for s in e["surface"]).rstrip() + ")"
        if len(e["surface"]) == 1:
            surf = f'("{e["surface"][0]}",)'
        scope = _py_literal(e["scope"])
        ra = _py_literal(e["rest_analogue"])
        # json.dumps escapes non-BMP text as a surrogate pair, which is not a valid Python string
        # literal for that character, so a title must stay inside the Basic Multilingual Plane.
        # A lone surrogate passes that range test but cannot be encoded as UTF-8, so refuse it too.
        if any(ord(ch) > 0xFFFF for ch in str(e["title"])):
            raise RegistryError(f"error title for {e['code']!r} must stay in the BMP")
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in str(e["title"])):
            raise RegistryError(f"error title for {e['code']!r} must not contain a lone surrogate")
        cc = "None" if e["close_code"] is None else str(e["close_code"])
        rt = "True" if e["retryable"] else "False"
        out.append(
            f'    ErrorCode.{_member(e["code"])}: ErrorMeta({surf}, {scope}, '
            f'{rt}, {ra}, {cc}, {json.dumps(e["title"])}),'
        )
    out += [
        "}",
        "",
        "#: Codes legal on the WebSocket (23-ws-protocol.md 10.2): WS-only plus dual-surface.",
        "WS_ERROR_CODES: Final[frozenset[ErrorCode]] = frozenset(",
        '    code for code, meta in ERROR_META.items() if "ws" in meta.surfaces',
        ")",
        "",
    ]
    return "\n".join(out)


def render_ts(entries: list[dict[str, Any]]) -> str:
    out = [
        "// GENERATED FILE - DO NOT EDIT BY HAND.",
        "// Generator: tools/errorcodes/generate.py (E17-T05).",
        f"// Source: {SRC_NOTE}. Edit the YAML and run `make gen`.",
        "",
        "export const ERROR_CODES = [",
    ]
    out += [f'  "{e["code"]}",' for e in entries]
    out += [
        "] as const;",
        "",
        "export type ErrorCode = (typeof ERROR_CODES)[number];",
        "",
        "export interface ErrorMeta {",
        '  readonly surfaces: readonly ("rest" | "ws")[];',
        "  readonly scope: string | null;",
        "  readonly retryable: boolean;",
        "  readonly restAnalogue: ErrorCode | null;",
        "  readonly closeCode: number | null;",
        "}",
        "",
        "export const ERROR_META: Readonly<Record<ErrorCode, ErrorMeta>> = {",
    ]
    for e in entries:
        surf = ", ".join(f'"{s}"' for s in e["surface"])
        scope = json.dumps(e["scope"])
        ra = json.dumps(e["rest_analogue"])
        cc = "null" if e["close_code"] is None else str(e["close_code"])
        out.append(
            f'  {e["code"]}: {{ surfaces: [{surf}], scope: {scope}, '
            f'retryable: {"true" if e["retryable"] else "false"}, restAnalogue: {ra}, '
            f"closeCode: {cc} }},"
        )
    out += [
        "};",
        "",
        "export const WS_ERROR_CODES: readonly ErrorCode[] = ERROR_CODES.filter((c) =>",
        '  ERROR_META[c].surfaces.includes("ws"),',
        ");",
        "",
    ]
    return "\n".join(out)


def render_all(openapi_text: str) -> dict[Path, str]:
    entries = load_registry(openapi_text)
    return {OUT_PY: render_py(entries), OUT_TS: render_ts(entries)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    outputs = render_all(OPENAPI.read_text(encoding="utf-8"))
    bad = 0
    for path, text in outputs.items():
        if args.check:
            cur = path.read_bytes().decode("utf-8") if path.exists() else ""
            if cur != text:
                print(f"[errorcodes] {path} is stale; run `make gen`.", file=sys.stderr)
                bad += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
