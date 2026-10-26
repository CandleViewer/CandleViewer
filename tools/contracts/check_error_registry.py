#!/usr/bin/env python3
"""E17-T05: blocking gate ``error_registry_single_source`` (23-ws-protocol.md 10.2).

Asserts (a) the section 10.2 Code column equals ``x-error-codes-ws`` union the
``surface: [rest, ws]`` subset of ``x-error-codes`` exactly; (b) every ``rest_analogue``
resolves to a REST code; (c) the generated enums equal a fresh regeneration byte for byte.
The table is parsed strictly: a malformed row fails the gate, it is never skipped.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.errorcodes import generate

MD = REPO / "docs" / "plan" / "23-ws-protocol.md"
SECTION = re.compile(r"^### 10\.2 Catalogue\s*$(.*?)(?=^#{2,3} )", re.MULTILINE | re.DOTALL)
CODE_CELL = re.compile(r"^`([a-z][a-z0-9_]*)`$")


def parse_md_codes(markdown: str) -> list[str]:
    """Code column of the 10.2 table, in order. Raises ValueError on any malformed row."""
    m = SECTION.search(markdown)
    if m is None:
        raise ValueError("section 10.2 Catalogue not found")
    rows = [ln.strip() for ln in m.group(1).splitlines() if ln.strip().startswith("|")]
    if len(rows) < 3:
        raise ValueError("section 10.2 table not found")
    header = [c.strip() for c in rows[0].strip("|").split("|")]
    if len(header) != 5 or header[0] != "Code":
        raise ValueError(f"section 10.2 table header unexpected: {header}")
    if not re.fullmatch(r"\|?[\s:|-]+\|?", rows[1]):
        raise ValueError("section 10.2 table separator row missing")
    codes: list[str] = []
    for row in rows[2:]:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) != len(header):
            raise ValueError(f"malformed 10.2 row (expected {len(header)} cells): {row}")
        cm = CODE_CELL.match(cells[0])
        if cm is None:
            raise ValueError(f"malformed 10.2 code cell {cells[0]!r} in row: {row}")
        if cm.group(1) in codes:
            raise ValueError(f"duplicate 10.2 code {cm.group(1)!r}")
        codes.append(cm.group(1))
    return codes


def check(markdown: str, openapi_text: str, generated: dict[Path, str] | None) -> list[str]:
    """All violations; empty list = pass. ``generated`` maps path -> committed text."""
    errors: list[str] = []
    try:
        entries = generate.load_registry(openapi_text)
    except generate.RegistryError as exc:
        return [f"registry: {exc}"]
    try:
        md_codes = set(parse_md_codes(markdown))
    except ValueError as exc:
        return [f"23-ws-protocol.md: {exc}"]
    registry_ws = {e["code"] for e in entries if "ws" in e["surface"]}
    for code in sorted(md_codes - registry_ws):
        errors.append(f"orphan code in 23-ws-protocol.md 10.2 but not in the registry: {code}")
    for code in sorted(registry_ws - md_codes):
        errors.append(f"orphan code in the registry (ws surface) but not in 10.2: {code}")
    rest = {e["code"] for e in entries if "rest" in e["surface"]}
    for e in entries:
        ra = e["rest_analogue"]
        if ra is not None and ra not in rest:
            errors.append(f"dangling rest_analogue: {e['code']} -> {ra} (no such REST code)")
    if generated is not None:
        try:
            fresh = {
                generate.OUT_PY: generate.render_py(entries),
                generate.OUT_TS: generate.render_ts(entries),
            }
        except generate.RegistryError as exc:
            return [*errors, f"registry: {exc}"]
        for path, text in fresh.items():
            if generated.get(path) != text:
                errors.append(f"generated file not byte-identical to regeneration: {path}")
    return errors


def main() -> int:
    committed: dict[Path, str] = {}
    for p in (generate.OUT_PY, generate.OUT_TS):
        if p.exists():
            committed[p] = p.read_bytes().decode("utf-8")
    errs = check(
        MD.read_text(encoding="utf-8"),
        generate.OPENAPI.read_text(encoding="utf-8"),
        committed,
    )
    for e in errs:
        print(f"[error_registry_single_source] {e}", file=sys.stderr)
    if not errs:
        print("[error_registry_single_source] OK")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
