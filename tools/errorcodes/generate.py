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
SURFACES = frozenset({"rest", "ws"})
# RFC 6455 close codes: 1000-2999 protocol range, 3000-4999 registered/private use.
CLOSE_CODE_RANGE = range(1000, 5000)


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
                surface = _checked_surface(code, raw.get("surface", ["rest"]))
                scope = "any" if "ws" in surface else None
            else:
                surface = ["ws"]
                scope = raw.get("scope")
                if not scope:
                    raise RegistryError(f"{code}: WS code without scope")
            close_code = raw.get("close_code")
            if close_code is not None and (
                type(close_code) is not int or close_code not in CLOSE_CODE_RANGE
            ):
                raise RegistryError(
                    f"{code}: close_code must be null or an integer in 1000..4999, "
                    f"got {close_code!r}"
                )
            rest_analogue = raw.get("rest_analogue")
            for field, value in (("scope", scope), ("rest_analogue", rest_analogue)):
                if value is not None and not isinstance(value, str):
                    raise RegistryError(f"{code}: {field} must be a string or null")
            entries.append(
                {
                    "code": code,
                    "surface": surface,
                    "scope": scope,
                    "retryable": bool(raw.get("retryable", False)),
                    "rest_analogue": rest_analogue,
                    "close_code": close_code,
                    "title": str(raw.get("title", "")).strip(),
                }
            )
    return entries


def _checked_surface(code: str, value: object) -> list[str]:
    """``surface`` must be a list whose items (after strip and lower) are known surfaces."""
    if not isinstance(value, list):
        raise RegistryError(f"{code}: surface must be a list, got {value!r}")
    surface = [str(s).strip().lower() for s in value]
    for item in surface:
        if item not in SURFACES:
            raise RegistryError(f"{code}: surface {item!r} must be one of {sorted(SURFACES)}")
    return surface


def _checked_text(field: str, code: str, value: object) -> str | None:
    """Text emitted into a literal: a string in the BMP without a lone surrogate, or ``None``."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise RegistryError(f"{field} for {code!r} must be a string")
    # json.dumps escapes non-BMP text as a surrogate pair, which is not a valid Python string
    # literal for that character, so the text must stay inside the Basic Multilingual Plane.
    if any(ord(ch) > 0xFFFF for ch in value):
        raise RegistryError(f"{field} for {code!r} must stay in the BMP")
    # Defence in depth: json.dumps would escape a lone surrogate, but it can never be valid
    # UTF-8 text, so refuse it at the source.
    if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        raise RegistryError(f"{field} for {code!r} must not contain a lone surrogate")
    return value


def _py_literal(value: str | None) -> str:
    """A Python literal for ``str | None``: ``None`` for null, never a text replacement."""
    if value is not None and not isinstance(value, str):
        raise RegistryError(f"cannot emit {type(value).__name__} as a string literal")
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
        scope = _py_literal(_checked_text("scope", e["code"], e["scope"]))
        ra = _py_literal(_checked_text("rest_analogue", e["code"], e["rest_analogue"]))
        title = _checked_text("error title", e["code"], str(e["title"]))
        cc = "None" if e["close_code"] is None else str(e["close_code"])
        rt = "True" if e["retryable"] else "False"
        out.append(
            f'    ErrorCode.{_member(e["code"])}: ErrorMeta({surf}, {scope}, '
            f"{rt}, {ra}, {cc}, {json.dumps(title)}),"
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
