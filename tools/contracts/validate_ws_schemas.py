#!/usr/bin/env python3
"""E17-T01: the blocking ``ws_message_schemas`` gate.

1. Meta-validates every schema in ``ws-schemas.json`` against JSON Schema
   2020-12 (naming the offending ``$id`` and keyword).
2. Asserts every ``$ref`` resolves inside the bundle (naming referrer + target).
3. Validates every example frame of ``23-ws-protocol.md`` section 12 against
   the schema it claims to be an instance of (envelope + per-type payload).

Section 12 blocks are ``jsonc``: ``//`` comment lines are stripped *only* here
(schemas in 13-15 must stay strict JSON). Offline, stdlib + ``jsonschema``.

Usage: ``python tools/contracts/validate_ws_schemas.py --draft 2020-12``
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

REPO = Path(__file__).resolve().parents[2]
DEFAULT_MD = REPO / "docs" / "plan" / "23-ws-protocol.md"
DEFAULT_BUNDLE = REPO / "packages" / "protocol" / "ws-schemas.json"
BASE = "cv://ws/v1/"
ENVELOPE = BASE + "envelope.schema.json"

# Frame type -> payload schema file (snap/d resolve by channel family instead).
CONTROL_SCHEMA = {
    "hello": "hello",
    "welcome": "welcome",
    "auth": "auth",
    "auth_ok": "auth_ok",
    "sub": "sub",
    "sub_ok": "sub_ok",
    "unsub": "unsub",
    "unsub_ok": "unsub_ok",
    "ctl": "ctl",
    "ctl_ok": "ctl_ok",
    "resync": "resync",
    "revoked": "revoked",
    "ping": "heartbeat",
    "pong": "heartbeat",
    "bye": "bye",
}
CHANNEL_SCHEMA = {
    "book": "book",
    "trades": "trades",
    "bars": "bars",
    "footprint": "footprint",
    "heatmap": "heatmap",
    "profile": "profile",
    "metrics": "metrics",
    "ticker": "ticker",
    "liquidations": "liquidations",
    "orders": "orders",
    "positions": "positions",
    "executions": "executions",
    "wallet": "wallet",
    "trade_groups": "trade_groups",
    "rules": "rules",
    "alerts": "alerts",
    "recorder": "recorder",
    "system": "system",
    "machines": "machines",
}
SECTION12 = re.compile(r"^## 12\..*?(?=^## 13\.)", re.MULTILINE | re.DOTALL)
JSONC = re.compile(r"^```jsonc[ \t]*\r?\n(.*?)\r?\n```[ \t]*$", re.MULTILINE | re.DOTALL)
FRAME_START = re.compile(r"^(?:C→S|S→C)\s+(.*)$")
REF = "$ref"


def iter_refs(node: Any, path: str = "") -> Any:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == REF and isinstance(value, str):
                yield path, value
            else:
                yield from iter_refs(value, f"{path}/{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from iter_refs(value, f"{path}/{i}")


def build_registry(schemas: dict[str, Any]) -> Registry:
    registry: Registry = Registry()
    for sid, schema in schemas.items():
        registry = registry.with_resource(sid, Resource.from_contents(schema))
    return registry


def check_schemas(schemas: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for sid, schema in sorted(schemas.items()):
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            where = "/".join(str(p) for p in exc.path)
            kw = exc.validator or "?"
            errors.append(f"{sid}: invalid schema, keyword {kw!r} at /{where}: {exc.message}")
    registry = build_registry(schemas)
    for sid, schema in sorted(schemas.items()):
        resolver = registry.resolver(sid)
        for path, ref in iter_refs(schema):
            try:
                resolver.lookup(ref)
            except Exception as exc:  # noqa: BLE001 - referencing raises several types
                errors.append(
                    f"{sid}: dangling $ref {ref!r} at {path or '/'} - target missing ({type(exc).__name__})"
                )
    return errors


def _frame(lines: list[str], line_no: int) -> tuple[str, dict[str, Any]]:
    label = f"section-12 line {line_no}"
    try:
        return label, json.loads("\n".join(lines))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label}: example is not JSON: {exc}") from exc


def parse_examples(markdown: str) -> list[tuple[str, dict[str, Any]]]:
    """Return ``(label, frame)`` for every example frame in section 12."""
    m = SECTION12.search(markdown)
    if m is None:
        raise ValueError("could not locate section 12")
    frames: list[tuple[str, dict[str, Any]]] = []
    for block in JSONC.finditer(m.group(0)):
        first = m.group(0).count("\n", 0, block.start()) + 2
        current: list[str] = []
        start_line = first
        for offset, raw in enumerate(block.group(1).splitlines()):
            line = raw.rstrip()
            if line.lstrip().startswith("//") or not line.strip():
                continue
            fs = FRAME_START.match(line)
            if fs:
                if current:
                    frames.append(_frame(current, start_line))
                current = [fs.group(1)]
                start_line = first + offset
            else:
                current.append(line)
        if current:
            frames.append(_frame(current, start_line))
    return frames


def payload_schema_id(frame: dict[str, Any]) -> str | None:
    t = frame.get("t")
    if t in CONTROL_SCHEMA:
        return BASE + CONTROL_SCHEMA[t] + ".schema.json"
    if t in ("snap", "d") and frame.get("e", "j") == "j":
        family = str(frame.get("ch", "")).split(".")[0]
        if family in CHANNEL_SCHEMA:
            return BASE + CHANNEL_SCHEMA[family] + ".schema.json"
    return None  # binary payload or error frame: envelope-only


def check_examples(schemas: dict[str, Any], markdown: str) -> tuple[list[str], int]:
    registry = build_registry(schemas)
    errors: list[str] = []
    examples = parse_examples(markdown)
    for label, frame in examples:
        targets = [ENVELOPE]
        pid = payload_schema_id(frame)
        if pid:
            targets.append(pid)
        for target in targets:
            if target not in schemas:
                errors.append(f"{label}: schema {target} is not in the bundle")
                continue
            validator = Draft202012Validator(schemas[target], registry=registry)
            subject = frame if target == ENVELOPE else frame.get("p")
            for err in validator.iter_errors(subject):
                where = "/".join(str(p) for p in err.absolute_path)
                errors.append(
                    f"{label}: frame t={frame.get('t')!r} ch={frame.get('ch')!r} violates "
                    f"{target} keyword {err.validator!r} at /{where}: {err.message[:160]}"
                )
    return errors, len(examples)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draft", default="2020-12", choices=["2020-12"])
    ap.add_argument("--md", type=Path, default=DEFAULT_MD)
    ap.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    args = ap.parse_args(argv)
    schemas = json.loads(args.bundle.read_text(encoding="utf-8"))["schemas"]
    errors = check_schemas(schemas)
    ex_errors, n_examples = check_examples(schemas, args.md.read_text(encoding="utf-8"))
    errors += ex_errors
    print(f"[ws_message_schemas] schemas={len(schemas)} examples={n_examples} errors={len(errors)}")
    for line in errors:
        print(f"  FAIL {line}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
