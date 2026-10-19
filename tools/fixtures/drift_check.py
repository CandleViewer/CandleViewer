"""Payload-drift check (E08-T05, risk R6 "feed rot").

Derives *schema expectations* (field path -> JSON type) from the committed corpus
and compares a freshly captured sample against them. Values are ignored, so a
price move is not drift; a field that appears, disappears or changes JSON type
is. Exit 1 with a diff naming the stream and the field.

    python tools/fixtures/drift_check.py --sample <dir-of-fresh-.jsonl/.json>
    python tools/fixtures/drift_check.py --write-expectations   # refresh baseline

The scheduled workflow `.github/workflows/fixture-drift.yml` runs it on a sample
captured by `capture_fixture.py` and reports a failure on one open issue (#1849).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - script entry
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.fixtures.build_corpus import ROOT as CORPUS

EXPECTATIONS = CORPUS / "schema_expectations.json"
Schema = dict[str, dict[str, dict[str, Any]]]  # stream -> path -> {types, required}


def json_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int | float):
        return "number"
    if isinstance(v, str):
        return "string"
    return "array" if isinstance(v, list) else "object"


def _walk(v: Any, path: str, out: dict[str, set[str]]) -> None:
    out.setdefault(path, set()).add(json_type(v))
    if isinstance(v, dict):
        for k, child in v.items():
            _walk(child, f"{path}.{k}" if path else k, out)
    elif isinstance(v, list):
        for child in v:
            _walk(child, f"{path}[]", out)


def stream_of(msg: Any, fallback: str) -> str:
    """Stream key: WS `topic` with the symbol stripped (`publicTrade`), else `fallback`."""
    if isinstance(msg, dict) and isinstance(msg.get("topic"), str):
        head = msg["topic"].split(".")
        return ".".join(head[:-1]) if len(head) > 1 else head[0]
    return fallback


def infer(docs: Iterable[tuple[str, Any]]) -> Schema:
    """Per stream: every field path, its JSON types, and whether every doc carries it
    (delta-encoded streams legitimately omit fields, so only `required` ones can vanish)."""
    types: dict[str, dict[str, set[str]]] = {}
    seen: dict[str, dict[str, int]] = {}
    counts: dict[str, int] = {}
    for stream, doc in docs:
        one: dict[str, set[str]] = {}
        _walk(doc, "", one)
        counts[stream] = counts.get(stream, 0) + 1
        for p, t in one.items():
            types.setdefault(stream, {}).setdefault(p, set()).update(t)
            seen.setdefault(stream, {})[p] = seen.get(stream, {}).get(p, 0) + 1
    return {
        s: {
            p: {"types": sorted(t), "required": seen[s][p] == counts[s]}
            for p, t in sorted(fields.items())
        }
        for s, fields in sorted(types.items())
    }


def load_docs(directory: Path) -> list[tuple[str, Any]]:
    """`.jsonl` -> one doc per frame, keyed by topic; `.json` -> keyed by file stem
    with a trailing `_<SYMBOL>...`/`_pageN` suffix removed (e.g. `kline`)."""
    docs: list[tuple[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        if path.name.endswith(".manifest.json") or path.name in {
            "manifest.json",
            EXPECTATIONS.name,
        }:
            continue
        if path.suffix == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    msg = json.loads(line)
                    docs.append((stream_of(msg, path.stem), msg))
        elif path.suffix == ".json":
            stem = path.stem.split("_")[0] if not path.stem.startswith("error") else "error"
            docs.append((f"rest.{stem}", json.loads(path.read_text(encoding="utf-8"))))
    return docs


def diff(expected: Schema, sample: Schema) -> list[str]:
    """Drift lines `<stream>: <added|removed|retyped> field <path> ...` for every
    stream present in the sample (a sample need not cover every stream)."""
    out: list[str] = []
    for stream, got in sorted(sample.items()):
        want = expected.get(stream)
        if want is None:
            out.append(f"{stream}: unknown stream (no expectations)")
            continue
        for path in sorted(set(got) - set(want)):
            out.append(f"{stream}: added field {path} ({'|'.join(got[path]['types'])})")
        for path, spec in sorted(want.items()):
            if path not in got:
                if spec["required"]:
                    out.append(f"{stream}: removed field {path}")
            elif not set(got[path]["types"]) <= set(spec["types"]):
                was, now = "|".join(spec["types"]), "|".join(got[path]["types"])
                out.append(f"{stream}: retyped field {path} {was} -> {now}")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bybit payload-drift check (R6)")
    p.add_argument("--sample", type=Path, help="directory holding a fresh capture")
    p.add_argument("--expectations", type=Path, default=EXPECTATIONS)
    p.add_argument("--corpus", type=Path, default=CORPUS)
    p.add_argument("--write-expectations", action="store_true")
    p.add_argument("--report", type=Path, help="write the drift diff here (for the issue body)")
    ns = p.parse_args(argv)
    if ns.write_expectations:
        schema = infer(load_docs(ns.corpus))
        ns.expectations.write_text(json.dumps(schema, indent=1) + "\n", encoding="utf-8",
                                   newline="\n")  # fmt: skip
        print(f"wrote {len(schema)} stream expectations -> {ns.expectations}")
        return 0
    if ns.sample is None:
        p.error("--sample is required unless --write-expectations")
    expected: Schema = json.loads(ns.expectations.read_text(encoding="utf-8"))
    sample = infer(load_docs(ns.sample))
    if not sample:
        print("drift check: sample is empty - refusing to pass silently", file=sys.stderr)
        return 2
    drift = diff(expected, sample)
    if ns.report is not None:
        ns.report.write_text("\n".join(drift) + "\n", encoding="utf-8")
    if drift:
        print("PAYLOAD DRIFT DETECTED (R6):", file=sys.stderr)
        for line in drift:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"drift check: {len(sample)} stream(s) match expectations")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
